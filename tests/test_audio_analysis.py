import io
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from pathlib import Path

import numpy as np
import soundfile as sf

from app import app, build_events


class AudioAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_mp3_upload_succeeds(self):
        mp3_data = Path('song.mp3').read_bytes()
        response = self.client.post(
            '/api/analyze-audio',
            data={'audio': (io.BytesIO(mp3_data), 'song.mp3')},
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload['event_count'], 5)
        self.assertEqual(payload['events'][0]['payload'], 'Start')

    def test_silent_audio_uses_fallback_beats(self):
        sr = 22050
        y = np.zeros(sr * 2, dtype=np.float32)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            sf.write(tmp.name, y, sr)
            events, _tempo, duration = build_events(tmp.name)

        self.assertGreater(duration, 1.5)
        self.assertGreaterEqual(len(events), 4)
        self.assertEqual(events[0]['payload'], 'Start')
        self.assertEqual(events[-1]['payload'], 'Stop')

    def test_unsupported_extension_rejected(self):
        response = self.client.post(
            '/api/analyze-audio',
            data={'audio': (io.BytesIO(b'not-audio'), 'clip.txt')},
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn('Unsupported audio format', payload['error'])
        self.assertEqual(payload['code'], 'unsupported_audio_format')

    def test_missing_audio_field_rejected(self):
        response = self.client.post(
            '/api/analyze-audio',
            data={},
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn('No audio file uploaded', payload['error'])
        self.assertEqual(payload['code'], 'missing_audio')

    def test_send_to_robot_dry_run(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.2, 'kind': 'joystick', 'payload': [0, 65]},
            {'t': 1.4, 'kind': 'joystick', 'payload': [0, 0]},
            {'t': 1.6, 'kind': 'button', 'payload': 'Stop'},
        ]
        response = self.client.post('/api/send-to-robot', json={
            'base_url': 'http://192.168.4.1',
            'dry_run': True,
            'events': events,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['mode'], 'dry_run')
        # Safe bookends add an early neutral joystick event when one is missing.
        self.assertEqual(payload['event_count'], 5)
        self.assertEqual(payload['send_speed'], 1.0)

    def test_send_to_robot_dry_run_normalizes_base_url(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.1, 'kind': 'button', 'payload': 'Stop'},
        ]
        response = self.client.post('/api/send-to-robot', json={
            'base_url': '192.168.4.1/',
            'dry_run': True,
            'events': events,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['base_url'], 'http://192.168.4.1')

    def test_send_to_robot_rejects_invalid_event_timeline(self):
        response = self.client.post('/api/send-to-robot', json={
            'events': [{'t': -1, 'kind': 'joystick', 'payload': [0, 0]}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid robot send request', response.get_json()['error'])
        self.assertEqual(response.get_json()['code'], 'invalid_robot_send_request')

    def test_send_to_robot_rejects_invalid_send_speed(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.1, 'kind': 'button', 'payload': 'Stop'},
        ]
        response = self.client.post('/api/send-to-robot', json={
            'events': events,
            'send_speed': 0.1,
        })
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload['code'], 'invalid_robot_send_request')
        self.assertIn('send_speed must be between', payload['error'])

    def test_send_to_robot_dry_run_accepts_reduced_speed(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.2, 'kind': 'button', 'payload': 'Stop'},
        ]
        response = self.client.post('/api/send-to-robot', json={
            'base_url': 'http://192.168.4.1',
            'dry_run': True,
            'send_speed': 0.5,
            'events': events,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['send_speed'], 0.5)

    def test_send_to_robot_dry_run_bookends_early_events_without_reordering_failure(self):
        events = [
            {'t': 0.05, 'kind': 'joystick', 'payload': [10, 10]},
            {'t': 0.2, 'kind': 'button', 'payload': 'Stop'},
        ]
        response = self.client.post('/api/send-to-robot', json={
            'base_url': 'http://192.168.4.1',
            'dry_run': True,
            'events': events,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        # Safe bookends add a Start and early neutral joystick event.
        self.assertEqual(payload['event_count'], 4)

    def test_send_to_robot_network_error_includes_code_and_details(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.1, 'kind': 'button', 'payload': 'Stop'},
        ]
        with patch('app._send_event_timeline_to_robot', side_effect=URLError('timed out')):
            response = self.client.post('/api/send-to-robot', json={
                'base_url': 'http://192.168.4.1',
                'events': events,
            })

        self.assertEqual(response.status_code, 502)
        payload = response.get_json()
        self.assertEqual(payload['code'], 'robot_unreachable')
        self.assertIn('Could not reach robot', payload['error'])
        self.assertIn('timed out', payload['details'])

    def test_send_to_robot_worker_timeout_is_reported_as_unreachable(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.1, 'kind': 'button', 'payload': 'Stop'},
        ]
        with patch('app._send_event_timeline_to_robot', side_effect=TimeoutError('timed out')):
            response = self.client.post('/api/send-to-robot', json={
                'base_url': 'http://192.168.4.1',
                'events': events,
            })

        self.assertEqual(response.status_code, 502)
        payload = response.get_json()
        self.assertEqual(payload['code'], 'robot_unreachable')
        self.assertIn('timed out', payload['details'])

    def test_send_to_robot_unexpected_error_includes_debug_details(self):
        events = [
            {'t': 0.0, 'kind': 'button', 'payload': 'Start'},
            {'t': 0.1, 'kind': 'button', 'payload': 'Stop'},
        ]
        with patch('app._send_event_timeline_to_robot', side_effect=RuntimeError('boom')):
            response = self.client.post('/api/send-to-robot', json={
                'base_url': 'http://192.168.4.1',
                'events': events,
            })

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertEqual(payload['code'], 'robot_dispatch_failed')
        self.assertIn('RuntimeError', payload['details'])


if __name__ == '__main__':
    unittest.main()
