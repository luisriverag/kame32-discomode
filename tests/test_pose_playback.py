import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as backend


class PosePlaybackTests(unittest.TestCase):
    def setUp(self):
        self.client = backend.app.test_client()
        self.pose = {f's{i}': 90 for i in range(8)}
        self.events = backend._with_safe_bookends([{'t': 0, 'kind': 'pose', 'payload': self.pose},
                                                  {'t': .35, 'kind': 'pose', 'payload': self.pose}])

    def test_old_firmware_rejected_before_any_motion(self):
        with patch('app._robot_capabilities', return_value={}), patch('app._http_robot_get') as send:
            with self.assertRaisesRegex(ValueError, 'firmware'):
                backend._send_event_timeline_to_robot(self.events, 'http://robot.local')
        send.assert_not_called()

    def test_pose_stream_uses_one_lease_and_heartbeats(self):
        capabilities = {'pose': True, 'watchdog': True, 'lease_token': True}
        with patch('app._robot_capabilities', return_value=capabilities), patch('app._http_robot_get', return_value=200) as send:
            result = backend._send_event_timeline_to_robot(self.events, 'http://robot.local')
        self.assertEqual(result['sent'], len(self.events))
        calls = send.call_args_list
        self.assertTrue(any(call.args[1] == '/pose' for call in calls))
        self.assertTrue(any(call.args[1] == '/heartbeat' for call in calls))
        leases = {call.args[2]['lease'] for call in calls}
        self.assertEqual(len(leases), 1)
        self.assertEqual(calls[-1].args[2]['label'], 'Stop')
        self.assertEqual(calls[0].args[2]['mode'], 'pose')

    def test_pose_stream_never_inserts_gait_home_commands(self):
        self.assertFalse(any(event['kind'] == 'joystick' for event in self.events))
        self.assertEqual(self.events[0]['payload'], 'Start')
        self.assertEqual(self.events[-1]['payload'], 'Stop')

    def test_invalid_pose_is_rejected(self):
        for pose in ({}, {**self.pose, 's0': 181}, {**self.pose, 's0': True}):
            with self.assertRaises(ValueError):
                backend._validate_robot_events([{'t': 0, 'kind': 'pose', 'payload': pose}])

    def test_saved_move_send_defaults_to_dry_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(backend.app.config, {'MOVES_DB': str(Path(directory) / 'moves.sqlite3')}):
            frames = [{'t': t, 'pose': self.pose} for t in (0, 1)]
            self.client.put('/api/moves/Move1', json={'frames': frames})
            with patch('app._send_event_timeline_to_robot') as send:
                response = self.client.post('/api/moves/Move1/send', json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['mode'], 'dry_run')
            self.assertTrue(response.json['requires_pose_firmware'])
            send.assert_not_called()

    def test_live_saved_move_rejects_old_firmware(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(backend.app.config, {'MOVES_DB': str(Path(directory) / 'moves.sqlite3')}):
            frames = [{'t': t, 'pose': self.pose} for t in (0, 1)]
            self.client.put('/api/moves/Move1', json={'frames': frames})
            with patch('app._robot_capabilities', return_value={}), patch('app._http_robot_get') as send:
                response = self.client.post('/api/moves/Move1/send', json={'dry_run': False})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json['code'], 'robot_firmware_required')
            send.assert_not_called()

    def test_http_protocol_streams_saved_pose_with_scoped_lease(self):
        import json
        import os
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlsplit, parse_qs
        calls = []

        class Firmware(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlsplit(self.path)
                query = parse_qs(url.query)
                calls.append((url.path, query))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if url.path == '/capabilities':
                    self.wfile.write(json.dumps({'pose': True, 'watchdog': True, 'lease_token': True}).encode())
                else:
                    self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Firmware)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f'http://127.0.0.1:{server.server_port}'
            with tempfile.TemporaryDirectory() as directory, patch.dict(backend.app.config, {'MOVES_DB': str(Path(directory) / 'moves.sqlite3')}), patch.dict(os.environ, {'KAME32_ROBOT_ORIGINS': origin}):
                self.client.put('/api/moves/Move1', json={'frames': [{'t': 0, 'pose': self.pose}, {'t': .35, 'pose': self.pose}]})
                response = self.client.post('/api/moves/Move1/send', json={'base_url': origin, 'dry_run': False})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(calls[0][0], '/capabilities')
            self.assertTrue(any(path == '/heartbeat' for path, _ in calls))
            self.assertEqual(sum(path == '/pose' for path, _ in calls), 2)
            self.assertEqual(calls[-1][1]['label'], ['Stop'])
            leases = {query['lease'][0] for path, query in calls if path != '/capabilities'}
            self.assertEqual(len(leases), 1)
            self.assertFalse(any(path == '/joystick' for path, _ in calls))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
