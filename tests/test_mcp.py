"""Real MCP stdio round trip against an ephemeral local Flask server."""
import os
import tempfile
import threading
import unittest
from pathlib import Path

from werkzeug.serving import make_server
from app import app

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


@unittest.skipUnless(HAS_MCP, 'Optional MCP dependencies not installed')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_tools_resources_prompts_and_move_crud(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            previous = app.config.get('MOVES_DB')
            app.config['MOVES_DB'] = str(Path(directory) / 'moves.sqlite3')
            server = make_server('127.0.0.1', 0, app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env = dict(os.environ, KAME32_APP_URL=f'http://127.0.0.1:{server.server_port}', KAME32_AUDIO_DIR=directory)
            params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).resolve().parents[1] / 'mcp_server.py')], env=env)
            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        self.assertTrue({'get_status', 'analyze_audio', 'control_browser', 'dispatch_robot', 'save_move'} <= names)
                        self.assertEqual(len((await session.list_resources()).resources), 2)
                        self.assertEqual(len((await session.list_resource_templates()).resourceTemplates), 1)
                        self.assertEqual((await session.list_prompts()).prompts[0].name, 'teach_move')
                        prompt = await session.get_prompt('teach_move', {'goal': 'wave'})
                        self.assertIn('wave', prompt.messages[0].content.text)
                        self.assertTrue((await session.read_resource('kame32://status')).contents)
                        frames = [{'t': t, 'pose': {f's{i}': 90 for i in range(8)}} for t in (0, 1)]
                        saved = await session.call_tool('save_move', {'name': 'Move1', 'frames': frames})
                        self.assertFalse(saved.isError)
                        validated = await session.call_tool('validate_move', {'name': 'Move1'})
                        self.assertFalse(validated.isError)
                        self.assertTrue((await session.read_resource('kame32://moves/Move1')).contents)
                        invalid = await session.call_tool('save_move', {'name': 'Move2', 'frames': []})
                        self.assertTrue(invalid.isError)
                        import numpy as np
                        import soundfile as sf
                        sf.write(str(Path(directory) / 'silence.wav'), np.zeros(22050 * 2), 22050)
                        analyzed = await session.call_tool('analyze_audio', {'path': 'silence.wav'})
                        self.assertFalse(analyzed.isError)
                        self.assertFalse((await session.call_tool('cancel_robot_dispatch', {})).isError)
                        invalid_path = await session.call_tool('analyze_audio', {'path': '../outside.mp3'})
                        self.assertTrue(invalid_path.isError)
                        invalid_client = await session.call_tool('control_browser', {'client_id': 'missing', 'action': 'play'})
                        self.assertTrue(invalid_client.isError)
                        dry = await session.call_tool('validate_timeline', {'events': [{'t': 0, 'kind': 'button', 'payload': 'Stop'}]})
                        self.assertFalse(dry.isError)
                        self.assertFalse((await session.call_tool('delete_move', {'name': 'Move1'})).isError)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                if previous is None:
                    app.config.pop('MOVES_DB', None)
                else:
                    app.config['MOVES_DB'] = previous
