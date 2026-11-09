import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import app


class ControlAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.get('MOVES_DB')
        app.config['MOVES_DB'] = str(Path(self.temp.name) / 'moves.sqlite3')
        self.client = app.test_client()
        self.frames = [{'t': t, 'pose': {f's{i}': 90 for i in range(8)}} for t in (0, 1)]

    def tearDown(self):
        if self.old is None:
            app.config.pop('MOVES_DB', None)
        else:
            app.config['MOVES_DB'] = self.old
        self.temp.cleanup()

    def test_move_crud_and_validation(self):
        self.assertEqual(self.client.put('/api/moves/Move1', json={'frames': self.frames}).status_code, 200)
        self.assertEqual(self.client.get('/api/moves').json['Move1'], self.frames)
        self.assertEqual(self.client.get('/api/moves/Move1').json['frames'], self.frames)
        self.assertEqual(self.client.put('/api/moves/Move7', json={'frames': self.frames}).status_code, 400)
        for frames in ([], [{'t': 0, 'pose': {}}], self.frames[::-1]):
            self.assertEqual(self.client.put('/api/moves/Move2', json={'frames': frames}).status_code, 400)
        self.assertEqual(self.client.delete('/api/moves/Move1').status_code, 200)
        self.assertEqual(self.client.get('/api/moves/Move1').status_code, 404)

    def test_command_delivery_ack_and_expiry(self):
        ident = 'test-command-client'
        self.client.post('/api/browser-clients', json={'client_id': ident, 'page': 'TeachMoves'})
        response = self.client.post('/api/browser-commands', json={'client_id': ident, 'action': 'record'})
        self.assertEqual(response.status_code, 202)
        command_id = response.json['id']
        delivered = self.client.get('/api/browser-commands', query_string={'client_id': ident}).json
        self.assertTrue(any(c['id'] == command_id for c in delivered))
        self.assertEqual(self.client.get('/api/browser-commands', query_string={'client_id': ident}).json, [])
        self.assertEqual(self.client.post(f'/api/browser-commands/{command_id}', json={'client_id': 'other', 'status': 'completed'}).status_code, 400)
        self.assertEqual(self.client.post(f'/api/browser-commands/{command_id}', json={'client_id': ident, 'status': 'completed'}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/browser-commands/{command_id}').json['status'], 'completed')
        queued = self.client.post('/api/browser-commands', json={'client_id': ident, 'action': 'play'}).json
        with patch('control_api.time.monotonic', return_value=queued['created'] + 31):
            self.assertEqual(self.client.get(f"/api/browser-commands/{queued['id']}").json['status'], 'expired')

    def test_invalid_client_and_page_actions(self):
        self.assertEqual(self.client.post('/api/browser-clients', json={'client_id': [], 'page': 'DanceMode'}).status_code, 400)
        self.client.post('/api/browser-clients', json={'client_id': 'dance-test', 'page': 'DanceMode'})
        self.assertEqual(self.client.post('/api/browser-commands', json={'client_id': 'dance-test', 'action': 'record'}).status_code, 400)
        self.assertEqual(self.client.post('/api/browser-commands', json={'client_id': [], 'action': 'play'}).status_code, 404)
