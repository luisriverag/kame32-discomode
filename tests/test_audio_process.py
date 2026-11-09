import subprocess
import unittest
from unittest.mock import Mock, patch
import audio_process
from app import app


class AudioProcessTests(unittest.TestCase):
    def test_busy_admission_rejects_without_starting_worker(self):
        audio_process._SLOT.acquire()
        try:
            with self.assertRaises(audio_process.AnalysisBusy):
                audio_process.analyze_in_process('unused')
        finally:
            audio_process._SLOT.release()

    def test_timeout_kills_group_reaps_and_releases_slot(self):
        worker = Mock(pid=1234)
        worker.communicate.side_effect = subprocess.TimeoutExpired('worker', 1)
        with patch('audio_process.subprocess.Popen', return_value=worker), patch('audio_process.os.killpg') as kill:
            with self.assertRaises(audio_process.AnalysisTimeout):
                audio_process.analyze_in_process('unused', timeout=1)
            kill.assert_called_once()
            worker.wait.assert_called_once()
        self.assertTrue(audio_process._SLOT.acquire(blocking=False))
        audio_process._SLOT.release()

    def test_busy_upload_returns_structured_error_and_keeps_robot_status_available(self):
        import io
        with patch('app.analyze_in_process', side_effect=audio_process.AnalysisBusy):
            client = app.test_client()
            result = client.post('/api/analyze-audio', data={'audio': (io.BytesIO(b'audio'), 'test.wav')})
            self.assertEqual(result.status_code, 429)
            self.assertEqual(result.json['code'], 'audio_analysis_busy')
            self.assertEqual(client.get('/api/robot/status').status_code, 200)
