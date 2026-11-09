import unittest
from app import app


class PageTests(unittest.TestCase):
    def test_dance_mode_has_navigation_without_recording_controls(self):
        response = app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<title>DanceMode</title>', response.data)
        self.assertIn(b'href="/teach-moves"', response.data)
        self.assertNotIn(b'id="recordMacro"', response.data)

    def test_teach_moves_loads_recording_controls_and_shared_preview(self):
        response = app.test_client().get('/teach-moves')
        self.assertEqual(response.status_code, 200)
        for marker in (b'<title>TeachMoves</title>', b'id="recordMacro"',
                       b'id="macroSlots"', b'id="scene"', b'/static/teach.js'):
            self.assertIn(marker, response.data)
        self.assertEqual(app.test_client().get('/static/teach.js').status_code, 200)
