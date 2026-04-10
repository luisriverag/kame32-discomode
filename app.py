from __future__ import annotations

import logging
import os
import random
import socket
import tempfile
import time
from contextlib import redirect_stderr
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from io import StringIO
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import librosa
import numpy as np
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.logger.setLevel(logging.INFO)

ALLOWED_AUDIO_SUFFIXES = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}
ALLOWED_BUTTON_LABELS = {'A', 'B', 'C', 'X', 'Y', 'Z', 'Start', 'Stop'}
ROBOT_DEFAULT_BASE_URL = 'http://192.168.4.1'
ROBOT_MAX_EVENTS = 5000
ROBOT_MAX_SCRIPT_SECONDS = 600.0
ROBOT_CALL_TIMEOUT_SEC = 3.0
ROBOT_MIN_SEND_SPEED = 0.25
ROBOT_MAX_SEND_SPEED = 1.0
ROBOT_SAFE_NEUTRAL_JOYSTICK_AT_SEC = 0.15

_ROBOT_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _error_response(message: str, status: int, *, code: str | None = None, details: str | None = None):
    payload = {'error': message}
    if code:
        payload['code'] = code
    if details:
        payload['details'] = details
    return jsonify(payload), status


@app.errorhandler(413)
def request_entity_too_large(_err):
    return _error_response('Uploaded file is too large. Max size is 50 MB.', 413, code='upload_too_large')


DEMO_ROUTINES = {
    "mp3_style_demo": [
        {"t": 0.0, "kind": "button", "payload": "Start"},
        {"t": 0.2, "kind": "joystick", "payload": [0, 0]},
        {"t": 0.8, "kind": "joystick", "payload": [0, 70]},
        {"t": 1.8, "kind": "joystick", "payload": [20, 40]},
        {"t": 2.5, "kind": "joystick", "payload": [-20, 40]},
        {"t": 3.2, "kind": "button", "payload": "B"},
        {"t": 4.0, "kind": "joystick", "payload": [55, 0]},
        {"t": 4.9, "kind": "joystick", "payload": [-55, 0]},
        {"t": 5.8, "kind": "button", "payload": "X"},
        {"t": 7.4, "kind": "button", "payload": "Y"},
        {"t": 9.9, "kind": "button", "payload": "Z"},
        {"t": 11.4, "kind": "joystick", "payload": [0, 0]},
        {"t": 11.8, "kind": "button", "payload": "Stop"},
    ],
    "keyframe_groove": [
        {
            "label": "manual-pose groove",
            "frames": [
                {"t": 0.0, "pose": {"s0": 110, "s1": 70, "s2": 75, "s3": 105, "s4": 70, "s5": 110, "s6": 105, "s7": 75}},
                {"t": 0.6, "pose": {"s0": 95, "s1": 85, "s2": 85, "s3": 95, "s4": 85, "s5": 95, "s6": 95, "s7": 85}},
                {"t": 1.2, "pose": {"s0": 70, "s1": 110, "s2": 105, "s3": 75, "s4": 110, "s5": 70, "s6": 75, "s7": 105}},
                {"t": 1.8, "pose": {"s0": 95, "s1": 85, "s2": 85, "s3": 95, "s4": 85, "s5": 95, "s6": 95, "s7": 85}},
                {"t": 2.4, "pose": {"s0": 115, "s1": 65, "s2": 80, "s3": 110, "s4": 65, "s5": 115, "s6": 110, "s7": 80}},
                {"t": 3.0, "pose": {"s0": 90, "s1": 90, "s2": 80, "s3": 100, "s4": 90, "s5": 90, "s6": 100, "s7": 80}},
            ],
        }
    ],
}


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/api/presets')
def presets():
    return jsonify(DEMO_ROUTINES)


def zscore_normalize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    std = float(np.std(x))
    if std < 1e-9:
        return np.zeros_like(x)
    return (x - float(np.mean(x))) / std


def classify_section(rms: float, onset: float) -> str:
    score = 0.65 * rms + 0.35 * onset
    if score > 1.1:
        return 'high'
    if score > 0.2:
        return 'mid'
    return 'low'


def _sample_feature(times: np.ndarray, values: np.ndarray, t: float) -> float:
    idx = int(np.argmin(np.abs(times - t)))
    return float(values[idx])


def _fallback_beat_grid(duration: float, tempo: float | None) -> np.ndarray:
    if tempo is None or not np.isfinite(tempo) or tempo < 40 or tempo > 220:
        tempo = 110.0
    beat_period = 60.0 / float(tempo)
    beat_count = max(4, int(duration / beat_period) + 1)
    return np.linspace(0.0, max(0.0, duration - 1e-3), beat_count)


def build_events(audio_path: str, seed: int = 7) -> tuple[list[dict], float, float]:
    rng = random.Random(seed)
    decoder_stderr = StringIO()
    with redirect_stderr(decoder_stderr):
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
    decoder_notes = decoder_stderr.getvalue().strip()
    if decoder_notes:
        app.logger.info('Audio decoder notes while loading %s: %s', audio_path, decoder_notes)
    duration = float(librosa.get_duration(y=y, sr=sr))

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_raw, beat_frames = librosa.beat.beat_track(y=y, sr=sr, onset_envelope=onset_env, trim=False)
    tempo = float(np.atleast_1d(tempo_raw)[0]) if np.size(np.atleast_1d(tempo_raw)) else 0.0
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    if len(beat_times) < 4:
        app.logger.info('Sparse beat detection (%s beats); using fallback beat grid for %s', len(beat_times), audio_path)
        beat_times = _fallback_beat_grid(duration, tempo)

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_t = librosa.times_like(rms, sr=sr, hop_length=512)
    onset_t = librosa.times_like(onset_env, sr=sr)

    rms_z = zscore_normalize(rms)
    onset_z = zscore_normalize(onset_env)

    beat_strengths = []
    for t in beat_times:
        beat_strengths.append(
            (_sample_feature(rms_t, rms_z, float(t)), _sample_feature(onset_t, onset_z, float(t)))
        )

    events: list[dict] = []
    events.append({'t': 0.00, 'kind': 'button', 'payload': 'Start'})
    events.append({'t': 0.15, 'kind': 'joystick', 'payload': [0, 0]})

    strong_threshold = float(np.percentile([o for _, o in beat_strengths], 80))
    huge_threshold = float(np.percentile([r + o for r, o in beat_strengths], 90))
    last_big_move_t = -999.0

    for i, t in enumerate(beat_times[:-1]):
        t = float(t)
        next_t = float(beat_times[i + 1])
        gap = max(0.18, next_t - t)
        rms_i, onset_i = beat_strengths[i]
        section = classify_section(rms_i, onset_i)
        bar_pos = i % 8
        long_move_allowed = (t - last_big_move_t) > 2.2
        combo_score = rms_i + onset_i

        if bar_pos == 0 and combo_score >= huge_threshold and long_move_allowed:
            label = 'Y' if section == 'high' else 'X'
            events.append({'t': round(t, 3), 'kind': 'button', 'payload': label})
            events.append({'t': round(t + min(1.4, gap * 0.8), 3), 'kind': 'joystick', 'payload': [0, 0]})
            last_big_move_t = t
            continue

        if onset_i >= strong_threshold and long_move_allowed and gap > 0.42 and bar_pos in (2, 6):
            events.append({'t': round(t, 3), 'kind': 'button', 'payload': 'B'})
            events.append({'t': round(t + min(0.9, gap * 0.65), 3), 'kind': 'joystick', 'payload': [0, 0]})
            last_big_move_t = t
            continue

        swing = 55 if section == 'high' else 38 if section == 'mid' else 25
        forward = 65 if section == 'high' else 42 if section == 'mid' else 20

        if section == 'high':
            x = swing if (i % 2 == 0) else -swing
            yv = 18 if (i % 4 in (0, 1)) else -10
            events.append({'t': round(t, 3), 'kind': 'joystick', 'payload': [x, yv]})
            events.append({'t': round(t + gap * 0.55, 3), 'kind': 'joystick', 'payload': [int(-x // 2), 0]})
            events.append({'t': round(t + gap * 0.90, 3), 'kind': 'joystick', 'payload': [0, 0]})
        elif section == 'mid':
            x = 28 if (i % 4 in (0, 3)) else -28
            yv = forward if (i % 2 == 0) else forward // 2
            events.append({'t': round(t, 3), 'kind': 'joystick', 'payload': [x, yv]})
            events.append({'t': round(t + gap * 0.65, 3), 'kind': 'joystick', 'payload': [0, 0]})
        else:
            x = 20 if (i % 2 == 0) else -20
            events.append({'t': round(t, 3), 'kind': 'joystick', 'payload': [x, 8]})
            events.append({'t': round(t + gap * 0.70, 3), 'kind': 'joystick', 'payload': [0, 0]})

        if bar_pos == 7 and section != 'low' and long_move_allowed and rng.random() < 0.35:
            label = 'Z' if section == 'mid' else 'X'
            stamp = t + gap * 0.25
            events.append({'t': round(stamp, 3), 'kind': 'button', 'payload': label})
            last_big_move_t = stamp

    events.append({'t': round(duration + 0.10, 3), 'kind': 'joystick', 'payload': [0, 0]})
    events.append({'t': round(duration + 0.20, 3), 'kind': 'button', 'payload': 'Stop'})

    events.sort(key=lambda e: float(e['t']))
    compact: list[dict] = []
    last_joy = None
    last_joy_t = -999.0
    for event in events:
        if event['kind'] == 'joystick':
            payload = tuple(int(v) for v in event['payload'])
            if payload == last_joy and (float(event['t']) - last_joy_t) < 0.15:
                continue
            last_joy = payload
            last_joy_t = float(event['t'])
            event = {**event, 'payload': list(payload)}
        compact.append(event)

    return compact, tempo, duration


def _normalize_robot_base_url(value: str | None) -> str:
    candidate = (value or ROBOT_DEFAULT_BASE_URL).strip()
    if not candidate:
        candidate = ROBOT_DEFAULT_BASE_URL
    if not candidate.startswith('http://') and not candidate.startswith('https://'):
        candidate = f'http://{candidate}'
    return candidate.rstrip('/')


def _http_robot_get(base_url: str, path: str, params: dict) -> int:
    query = urlencode(params)
    url = f'{base_url}{path}?{query}'
    try:
        with urlopen(url, timeout=ROBOT_CALL_TIMEOUT_SEC) as response:
            return int(getattr(response, 'status', 200))
    except (TimeoutError, socket.timeout) as err:
        raise URLError(f'timed out contacting {url}') from err


def _validate_send_speed(raw_value: object) -> float:
    if raw_value is None:
        return 1.0
    speed = float(raw_value)
    if not np.isfinite(speed):
        raise ValueError('send_speed must be a finite number.')
    if speed < ROBOT_MIN_SEND_SPEED or speed > ROBOT_MAX_SEND_SPEED:
        raise ValueError(f'send_speed must be between {ROBOT_MIN_SEND_SPEED:.2f} and {ROBOT_MAX_SEND_SPEED:.2f}.')
    return speed


def _validate_robot_events(events: object) -> list[dict]:
    if not isinstance(events, list) or not events:
        raise ValueError('events must be a non-empty array.')
    if len(events) > ROBOT_MAX_EVENTS:
        raise ValueError(f'event count exceeds max ({ROBOT_MAX_EVENTS}).')

    normalized = []
    last_t = -1e9
    for raw in events:
        if not isinstance(raw, dict):
            raise ValueError('each event must be an object.')
        kind = str(raw.get('kind', '')).strip().lower()
        t = float(raw.get('t', 0.0))
        if not np.isfinite(t) or t < 0:
            raise ValueError('event time "t" must be a finite number >= 0.')
        if t < last_t:
            raise ValueError('events must be sorted by ascending "t".')
        last_t = t

        if kind == 'joystick':
            payload = raw.get('payload')
            if not isinstance(payload, list) or len(payload) != 2:
                raise ValueError('joystick payload must be [x, y].')
            x = int(payload[0])
            y = int(payload[1])
            normalized.append({'t': t, 'kind': 'joystick', 'payload': [x, y]})
            continue

        if kind == 'button':
            label = str(raw.get('payload', '')).strip()
            if label not in ALLOWED_BUTTON_LABELS:
                raise ValueError(f'unsupported button label: {label}')
            normalized.append({'t': t, 'kind': 'button', 'payload': label})
            continue

        raise ValueError(f'unsupported event kind: {kind}')

    if normalized[-1]['t'] > ROBOT_MAX_SCRIPT_SECONDS:
        raise ValueError(f'last event exceeds max timeline ({ROBOT_MAX_SCRIPT_SECONDS}s).')
    return normalized


def _with_safe_bookends(events: object) -> list[dict]:
    if not isinstance(events, list):
        raise ValueError('events must be a non-empty array.')

    out = [dict(event) if isinstance(event, dict) else event for event in events]
    if not out:
        return out

    start_event = {'t': 0.0, 'kind': 'button', 'payload': 'Start'}
    has_start = any(
        isinstance(event, dict)
        and str(event.get('kind', '')).strip().lower() == 'button'
        and str(event.get('payload', '')).strip() == 'Start'
        for event in out
    )
    if not has_start:
        out.insert(0, start_event)

    has_neutral_joystick = any(
        isinstance(event, dict)
        and str(event.get('kind', '')).strip().lower() == 'joystick'
        and isinstance(event.get('payload'), list)
        and len(event.get('payload')) == 2
        and int(event.get('payload')[0]) == 0
        and int(event.get('payload')[1]) == 0
        and float(event.get('t', -1.0)) <= ROBOT_SAFE_NEUTRAL_JOYSTICK_AT_SEC
        for event in out
    )
    if not has_neutral_joystick:
        out.append({'t': ROBOT_SAFE_NEUTRAL_JOYSTICK_AT_SEC, 'kind': 'joystick', 'payload': [0, 0]})

    has_stop = any(
        isinstance(event, dict)
        and str(event.get('kind', '')).strip().lower() == 'button'
        and str(event.get('payload', '')).strip() == 'Stop'
        for event in out
    )
    if not has_stop:
        latest_t = max(float(event.get('t', 0.0)) for event in out if isinstance(event, dict))
        out.append({'t': round(latest_t + 0.1, 3), 'kind': 'button', 'payload': 'Stop'})

    out.sort(key=lambda event: float(event.get('t', 0.0)) if isinstance(event, dict) else 0.0)
    return out


def _send_event_timeline_to_robot(events: list[dict], base_url: str, send_speed: float = 1.0) -> dict:
    start = time.monotonic()
    first_t = float(events[0]['t'])
    dispatches = []

    for event in events:
        target_sec = max(0.0, (float(event['t']) - first_t) / send_speed)
        elapsed = time.monotonic() - start
        if target_sec > elapsed:
            time.sleep(target_sec - elapsed)

        if event['kind'] == 'joystick':
            x, y = event['payload']
            status = _http_robot_get(base_url, '/joystick', {'x': int(x), 'y': int(y)})
            dispatches.append({'t': event['t'], 'kind': 'joystick', 'payload': [int(x), int(y)], 'status': status})
        else:
            label = str(event['payload'])
            status = _http_robot_get(base_url, '/button', {'label': label})
            dispatches.append({'t': event['t'], 'kind': 'button', 'payload': label, 'status': status})

    elapsed_total = time.monotonic() - start
    return {
        'sent': len(dispatches),
        'elapsed': round(elapsed_total, 3),
        'dispatches': dispatches,
        'send_speed': float(send_speed),
    }


@app.post('/api/analyze-audio')
def analyze_audio():
    if 'audio' not in request.files:
        return _error_response('No audio file uploaded. Use form field name "audio".', 400, code='missing_audio')

    upload = request.files['audio']
    if not upload or not upload.filename:
        return _error_response('No file selected.', 400, code='missing_filename')

    filename = secure_filename(upload.filename)
    suffix = Path(filename).suffix or '.mp3'
    if suffix.lower() not in ALLOWED_AUDIO_SUFFIXES:
        return _error_response('Unsupported audio format. Allowed: mp3, wav, ogg, m4a, flac.', 400, code='unsupported_audio_format')

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            upload.save(temp_file)
            temp_path = temp_file.name

        events, tempo, duration = build_events(temp_path)
        return jsonify({
            'filename': filename,
            'tempo': round(float(tempo), 2),
            'duration': round(float(duration), 3),
            'events': events,
            'event_count': len(events),
        })
    except Exception:
        app.logger.exception('Audio analysis failed for upload %s', filename)
        return _error_response('Audio analysis failed. Verify the file is a valid, non-corrupt audio clip.', 400, code='audio_analysis_failed')
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@app.post('/api/send-to-robot')
def send_to_robot():
    payload = request.get_json(silent=True) or {}
    base_url = _normalize_robot_base_url(payload.get('base_url'))
    dry_run = bool(payload.get('dry_run', False))
    try:
        events = _validate_robot_events(_with_safe_bookends(payload.get('events')))
        send_speed = _validate_send_speed(payload.get('send_speed'))
    except (TypeError, ValueError) as err:
        return _error_response(f'Invalid robot send request: {err}', 400, code='invalid_robot_send_request')

    if dry_run:
        return jsonify({
            'ok': True,
            'mode': 'dry_run',
            'base_url': base_url,
            'event_count': len(events),
            'timeline_seconds': round(float(events[-1]['t']) - float(events[0]['t']), 3),
            'send_speed': send_speed,
        })

    future = _ROBOT_EXECUTOR.submit(_send_event_timeline_to_robot, events, base_url, send_speed)
    try:
        result = future.result(timeout=ROBOT_MAX_SCRIPT_SECONDS + 15.0)
    except FutureTimeoutError as err:
        if future.done():
            app.logger.exception('Robot dispatch network timeout for %s events to %s', len(events), base_url)
            return _error_response(
                f'Could not reach robot at {base_url}. Check Wi-Fi and power.',
                502,
                code='robot_unreachable',
                details=str(err),
            )
        future.cancel()
        app.logger.exception('Robot dispatch timed out for %s events to %s', len(events), base_url)
        return _error_response('Robot dispatch timed out.', 504, code='robot_dispatch_timeout', details=f'Timeline execution exceeded {ROBOT_MAX_SCRIPT_SECONDS + 15.0:.0f}s timeout.')
    except URLError as err:
        app.logger.exception('Robot dispatch network error to %s', base_url)
        return _error_response(f'Could not reach robot at {base_url}. Check Wi-Fi and power.', 502, code='robot_unreachable', details=str(getattr(err, 'reason', err)))
    except Exception as err:
        app.logger.exception('Robot dispatch failed for %s events to %s', len(events), base_url)
        return _error_response('Robot dispatch failed unexpectedly.', 500, code='robot_dispatch_failed', details=f'{type(err).__name__}: {err}')

    return jsonify({
        'ok': True,
        'mode': 'live',
        'base_url': base_url,
        'event_count': len(events),
        'sent': result['sent'],
        'elapsed': result['elapsed'],
        'dispatches': result['dispatches'],
        'send_speed': result['send_speed'],
    })


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', '').strip().lower() in {'1', 'true', 'yes'}
    app.run(debug=debug_mode, host='127.0.0.1', port=5000)
