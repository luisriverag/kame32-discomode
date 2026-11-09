import threading
import unittest
from unittest.mock import patch, Mock
from urllib.error import URLError, HTTPError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import app as backend


class RobotSafetyTests(unittest.TestCase):
    def setUp(self):
        self.capabilities = patch('app._robot_capabilities', return_value={}).start()
        self.addCleanup(patch.stopall)
        self.client = backend.app.test_client()
        self.events = [{'t': 0, 'kind': 'button', 'payload': 'Start'},
                       {'t': 1, 'kind': 'button', 'payload': 'Stop'}]

    def test_malformed_requests_are_structured_400(self):
        for payload in ([1], None, {'base_url': 1}, {'dry_run': 'false'},
                        {'base_url': 'http://user:pass@robot.local'},
                        {'base_url': 'http://robot.local/path'},
                        {'base_url': 'ftp://robot.local'}):
            with self.subTest(payload=payload):
                response = self.client.post('/api/send-to-robot', json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json['code'], 'invalid_robot_send_request')

    def test_joystick_range_and_types(self):
        for value in (101, -101, 0.5, True, '20', float('inf')):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    backend._validate_robot_events([{'t': 0, 'kind': 'joystick', 'payload': [value, 0]}])
        self.assertEqual(backend._validate_robot_events([{'t': 0, 'kind': 'joystick', 'payload': [-100, 100]}])[0]['payload'], [-100, 100])

    def test_bookends_enforce_boundaries_and_do_not_mutate(self):
        events = [{'t': 0, 'kind': 'button', 'payload': 'Stop'},
                  {'t': 1, 'kind': 'button', 'payload': 'Start'},
                  {'t': 2, 'kind': 'joystick', 'payload': [10, 10]}]
        out = backend._with_safe_bookends(events)
        self.assertEqual(out[0], {'t': 0, 'kind': 'button', 'payload': 'Start'})
        self.assertEqual(out[1]['payload'], [0, 0])
        self.assertEqual(out[-2]['payload'], [0, 0])
        self.assertEqual(out[-1]['payload'], 'Stop')
        self.assertEqual(len(events), 3)

    def test_route_rejects_unsorted_events(self):
        response = self.client.post('/api/send-to-robot', json={'dry_run': True, 'events': self.events[::-1]})
        self.assertEqual(response.status_code, 400)

    def test_unconfigured_destination_never_dispatches(self):
        with patch('app._send_event_timeline_to_robot') as send:
            response = self.client.post('/api/send-to-robot', json={'base_url': 'http://example.invalid', 'events': self.events})
        self.assertEqual(response.json['code'], 'robot_destination_not_allowed')
        send.assert_not_called()

    def test_configured_destination_dispatches(self):
        result = {'sent': 4, 'elapsed': 1, 'dispatches': [], 'send_speed': 1}
        with patch.dict('os.environ', {'KAME32_ROBOT_ORIGINS': 'http://robot.local'}), patch('app._send_event_timeline_to_robot', return_value=result):
            response = self.client.post('/api/send-to-robot', json={'base_url': 'http://robot.local', 'events': self.events})
        self.assertEqual(response.status_code, 200)

    def test_busy_slot_prevents_queueing(self):
        backend._ROBOT_SLOT.acquire()
        try:
            with patch('app._send_event_timeline_to_robot') as send:
                response = self.client.post('/api/send-to-robot', json={'events': self.events})
            self.assertEqual(response.status_code, 409)
            send.assert_not_called()
        finally:
            backend._ROBOT_SLOT.release()

    def test_failure_attempts_both_stop_commands(self):
        with patch('app._http_robot_get', side_effect=[URLError('private detail'), URLError('offline'), 200]) as get:
            with self.assertRaises(URLError):
                backend._send_event_timeline_to_robot(self.events, 'http://192.168.4.1')
        self.assertEqual(get.call_args_list[-2].args[1:], ('/joystick', {'x': 0, 'y': 0}))
        self.assertEqual(get.call_args_list[-1].args[1:], ('/button', {'label': 'Stop'}))

    def test_cancellation_interrupts_wait_and_stops(self):
        cancel = threading.Event()
        cancel.set()
        with patch('app._http_robot_get', return_value=200) as get:
            with self.assertRaises(TimeoutError):
                backend._send_event_timeline_to_robot(self.events, 'http://192.168.4.1', cancel=cancel)
        self.assertEqual(get.call_count, 2)

    def test_deadline_accounts_for_send_speed(self):
        future = Mock()
        future.result.return_value = {'sent': 4, 'elapsed': 1, 'dispatches': [], 'send_speed': 0.25}
        future.add_done_callback.side_effect = lambda callback: callback(future)
        with patch('app._ROBOT_EXECUTOR.submit', return_value=future):
            response = self.client.post('/api/send-to-robot', json={'events': self.events, 'send_speed': 0.25})
        self.assertEqual(response.status_code, 200)
        future.result.assert_called_once_with(timeout=19.0)

    def test_timeout_requests_cancellation_and_holds_slot_until_worker_finishes(self):
        future = Mock()
        future.result.side_effect = backend.FutureTimeoutError()
        future.done.return_value = False
        future.cancel.return_value = False
        callback = []
        future.add_done_callback.side_effect = callback.append
        try:
            with patch('app._ROBOT_EXECUTOR.submit', return_value=future) as submit:
                response = self.client.post('/api/send-to-robot', json={'events': self.events})
            self.assertEqual(response.status_code, 504)
            self.assertTrue(submit.call_args.args[-1].is_set())
            self.assertFalse(backend._ROBOT_SLOT.acquire(blocking=False))
        finally:
            if callback:
                callback[0](future)

    def test_network_error_details_are_redacted(self):
        with patch('app._send_event_timeline_to_robot', side_effect=URLError('sensitive server detail')):
            response = self.client.post('/api/send-to-robot', json={'events': self.events})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('sensitive', response.get_data(as_text=True))

    def test_cancel_active_dispatch_interrupts_and_releases_slot(self):
        started = threading.Event()
        responses = []

        def get(*args):
            started.set()
            return 200

        def send():
            with backend.app.test_client() as client:
                responses.append(client.post('/api/send-to-robot', json={'events': [
                    {'t': 0, 'kind': 'button', 'payload': 'Start'},
                    {'t': 10, 'kind': 'button', 'payload': 'Stop'}]}))

        with patch('app._http_robot_get', side_effect=get) as http:
            thread = threading.Thread(target=send)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                response = self.client.post('/api/robot/cancel')
                self.assertEqual(response.status_code, 202)
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(responses[0].json['code'], 'robot_dispatch_cancelled')
                self.assertFalse(self.client.get('/api/robot/status').json['active'])
                self.assertEqual(http.call_args_list[-1].args[1:], ('/button', {'label': 'Stop'}))
            finally:
                self.client.post('/api/robot/cancel')
                thread.join(2)

    def test_http_robot_get_does_not_follow_redirects(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/redirected')
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with self.assertRaises(HTTPError) as caught:
                backend._http_robot_get(f'http://127.0.0.1:{server.server_port}', '/button', {'label': 'Stop'})
            self.assertEqual(caught.exception.code, 302)
            self.assertEqual(paths, ['/button?label=Stop'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
