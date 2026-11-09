import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as backend


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = patch.dict(backend.app.config, {'MOVES_DB': str(Path(self.directory.name) / 'moves.sqlite3')})
        self.config.start()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.config.stop)
        self.client = backend.app.test_client()
        self.frames = [{'t': t, 'pose': {f's{i}': 90 for i in range(8)}} for t in (0, .01)]
        self.commands = [{'t': 0, 'kind': 'joystick', 'payload': [0, 70]},
                         {'t': .01, 'kind': 'button', 'payload': 'Stop'}]

    def save(self, events=None):
        return self.client.put('/api/moves/Move1', json={'frames': self.frames, 'events': events})

    def test_stock_recording_persists_and_dry_runs(self):
        self.assertEqual(self.save(self.commands).status_code, 200)
        move = self.client.get('/api/moves/Move1').json
        self.assertTrue(move['stock_compatible'])
        self.assertTrue(move['events'])
        response = self.client.post('/api/moves/Move1/send', json={'playback_mode': 'stock'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['requires_pose_firmware'])
        self.assertTrue(response.json['stock_compatible'])

    def test_manual_servo_move_cannot_be_approximated_for_stock(self):
        self.save()
        response = self.client.post('/api/moves/Move1/send', json={'playback_mode': 'stock'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Re-record', response.json['error'])

    def test_auto_falls_back_to_commands_without_sending_pose(self):
        self.save(self.commands)
        with patch('app._robot_capabilities', return_value={}), patch('app._http_robot_get', return_value=200) as send:
            response = self.client.post('/api/moves/Move1/send', json={'dry_run': False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['playback_mode'], 'stock')
        self.assertFalse(response.json['watchdog_active'])
        self.assertFalse(any(call.args[1] in {'/pose', '/heartbeat'} for call in send.call_args_list))
        self.assertTrue(any(call.args[1] == '/joystick' and call.args[2]['y'] == 70 for call in send.call_args_list))

    def test_auto_prefers_pose_on_updated_firmware(self):
        self.save(self.commands)
        caps = {'pose': True, 'watchdog': True, 'lease_token': True}
        with patch('app._robot_capabilities', return_value=caps), patch('app._http_robot_get', return_value=200) as send:
            response = self.client.post('/api/moves/Move1/send', json={'dry_run': False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['playback_mode'], 'pose')
        self.assertTrue(any(call.args[1] == '/pose' for call in send.call_args_list))

    def test_invalid_stock_commands_do_not_overwrite_move(self):
        self.save(self.commands)
        invalid = [{'t': .5, 'kind': 'button', 'payload': 'X'}]
        self.assertEqual(self.save(invalid).status_code, 400)
        self.assertTrue(self.client.get('/api/moves/Move1').json['stock_compatible'])
        self.assertEqual(self.save([{'t': {}, 'kind': 'button', 'payload': 'X'}]).status_code, 400)
        self.assertEqual(self.save([{'t': 0, 'kind': 'pose', 'payload': self.frames[0]['pose']}]).status_code, 400)

    def test_stock_button_timeout_allows_blocking_routines(self):
        events = backend._with_safe_bookends([{'t': 0, 'kind': 'button', 'payload': 'Y'}])
        with patch('app._robot_capabilities', return_value={}), patch('app._http_robot_get', return_value=200) as send:
            backend._send_event_timeline_to_robot(events, 'http://robot.local')
        button = next(call for call in send.call_args_list if call.args[2].get('label') == 'Y')
        self.assertEqual(button.kwargs['timeout'], 8)
