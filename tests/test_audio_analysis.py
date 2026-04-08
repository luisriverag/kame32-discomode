import io
import tempfile
import unittest
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
        self.assertIn('Unsupported audio format', response.get_json()['error'])

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
        self.assertEqual(payload['event_count'], 4)

    def test_send_to_robot_rejects_invalid_event_timeline(self):
        response = self.client.post('/api/send-to-robot', json={
            'events': [{'t': -1, 'kind': 'joystick', 'payload': [0, 0]}],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('Invalid event timeline', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
