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


def _resolve_log_level(raw_level: str | None) -> int:
    candidate = str(raw_level or '').strip().upper()
    if not candidate:
        return logging.INFO
    if candidate.isdigit():
        value = int(candidate)
        return value if value >= 0 else logging.INFO
    return getattr(logging, candidate, logging.INFO)


_configured_log_level = _resolve_log_level(os.getenv('KAME32_LOG_LEVEL'))
app.logger.setLevel(_configured_log_level)

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
    if x.size == 0:
        return np.zeros_like(x)
    lo, hi = np.percentile(x, [5, 95])
    x = np.clip(x, lo, hi)
    std = float(np.std(x))
    if std < 1e-9:
        return np.zeros_like(x)
    return (x - float(np.mean(x))) / std


def classify_section(energy: float, peak: float, transition: float, *, hi_energy: float, lo_energy: float, hi_peak: float, hi_transition: float) -> str:
    if energy >= hi_energy or peak >= hi_peak or transition >= hi_transition:
        return 'high'
    if energy <= lo_energy and peak < hi_peak * 0.7:
        return 'low'
    return 'mid'


def _sample_feature(times: np.ndarray, values: np.ndarray, t: float) -> float:
    idx = int(np.argmin(np.abs(times - t)))
    return float(values[idx])


def _fallback_beat_grid(duration: float, tempo: float | None) -> np.ndarray:
    if tempo is None or not np.isfinite(tempo) or tempo < 40 or tempo > 220:
        tempo = 110.0
    beat_period = 60.0 / float(tempo)
    beat_count = max(4, int(duration / beat_period) + 1)
    return np.linspace(0.0, max(0.0, duration - 1e-3), beat_count)


def _infer_bar_offset(accent: np.ndarray, bass: np.ndarray) -> int:
    if len(accent) < 8:
        return 0

    scores = []
    for offset in range(4):
        idx = np.arange(offset, len(accent), 4)
        if len(idx) == 0:
            scores.append(-1e9)
            continue
        score = float(np.mean(accent[idx] + 0.35 * bass[idx]))
        scores.append(score)
    return int(np.argmax(scores))


def _smooth_section_labels(labels: list[str]) -> list[str]:
    if len(labels) < 3:
        return labels

    smoothed = labels[:]
    for i in range(1, len(labels) - 1):
        if labels[i - 1] == labels[i + 1] and labels[i] != labels[i - 1]:
            smoothed[i] = labels[i - 1]
    return smoothed


def _append_joystick(events: list[dict], t: float, x: int, y: int) -> None:
    events.append({'t': round(float(t), 3), 'kind': 'joystick', 'payload': [int(x), int(y)]})


def _emit_bar_pattern(events: list[dict], beat_times: np.ndarray, start_idx: int, section: str, accent: np.ndarray, brightness: np.ndarray, phrase_index: int) -> None:
    orientation = 1 if (phrase_index % 2 == 0) else -1
    mirror = -1 if ((start_idx // 4) % 2) else 1
    sign = orientation * mirror

    for local_beat in range(4):
        beat_idx = start_idx + local_beat
        if beat_idx >= len(beat_times) - 1:
            break

        t = float(beat_times[beat_idx])
        next_t = float(beat_times[beat_idx + 1])
        gap = max(0.18, next_t - t)
        beat_accent = float(accent[beat_idx])
        beat_brightness = float(brightness[beat_idx])

        if section == 'high':
            x = int(sign * (54 if local_beat in (0, 2) else -54))
            y = 18 if beat_brightness >= 0 else -10
            _append_joystick(events, t, x, y)
            _append_joystick(events, t + gap * 0.46, int(-x * 0.45), 0)
            if local_beat == 3 or beat_accent < 0:
                _append_joystick(events, t + gap * 0.86, 0, 0)
        elif section == 'mid':
            x = int(sign * (30 if local_beat in (0, 3) else -30))
            y = 24 if local_beat in (0, 2) else 12
            _append_joystick(events, t, x, y)
            if beat_accent > 0.35:
                _append_joystick(events, t + gap * 0.52, int(-x * 0.45), 0)
            _append_joystick(events, t + gap * 0.82, 0, 0)
        else:
            if local_beat in (0, 2):
                x = int(sign * (18 if local_beat == 0 else -18))
                _append_joystick(events, t, x, 8)
            _append_joystick(events, t + gap * 0.72, 0, 0)


def _compact_events(events: list[dict]) -> list[dict]:
    compact: list[dict] = []
    last_joy_payload: tuple[int, int] | None = None
    last_joy_t = -999.0

    for event in events:
        if event['kind'] == 'joystick':
            payload = tuple(int(v) for v in event['payload'])
            threshold = 0.28 if payload == (0, 0) else 0.12
            if payload == last_joy_payload and (float(event['t']) - last_joy_t) < threshold:
                continue
            last_joy_payload = payload
            last_joy_t = float(event['t'])
            event = {**event, 'payload': list(payload)}
        compact.append(event)
    return compact


def build_events(audio_path: str, seed: int = 7) -> tuple[list[dict], float, float]:
    del seed

    decoder_stderr = StringIO()
    with redirect_stderr(decoder_stderr):
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
    decoder_notes = decoder_stderr.getvalue().strip()
    if decoder_notes:
        app.logger.info('Audio decoder notes while loading %s: %s', audio_path, decoder_notes)
    else:
        app.logger.debug('Audio decoder produced no warnings for %s', audio_path)
    duration = float(librosa.get_duration(y=y, sr=sr))

    hop_length = 512
    y_harmonic, y_percussive = librosa.effects.hpss(y)
    onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr, hop_length=hop_length)
    tempo_raw, beat_frames = librosa.beat.beat_track(y=y_percussive, sr=sr, onset_envelope=onset_env, trim=False)
    tempo = float(np.atleast_1d(tempo_raw)[0]) if np.size(np.atleast_1d(tempo_raw)) else 0.0
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    if len(beat_times) < 8:
        app.logger.info('Sparse beat detection (%s beats); using fallback beat grid for %s', len(beat_times), audio_path)
        beat_times = _fallback_beat_grid(duration, tempo)

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
    spectral_centroid = librosa.feature.spectral_centroid(y=y_harmonic, sr=sr, hop_length=hop_length)[0]
    stft = np.abs(librosa.stft(y=y, n_fft=2048, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    bass_band = (freqs >= 20) & (freqs <= 180)
    bass_energy = np.mean(stft[bass_band], axis=0)

    rms_t = librosa.times_like(rms, sr=sr, hop_length=hop_length)
    onset_t = librosa.times_like(onset_env, sr=sr, hop_length=hop_length)
    centroid_t = librosa.times_like(spectral_centroid, sr=sr, hop_length=hop_length)
    bass_t = librosa.times_like(bass_energy, sr=sr, hop_length=hop_length)

    rms_z = zscore_normalize(rms)
    onset_z = zscore_normalize(onset_env)
    centroid_z = zscore_normalize(spectral_centroid)
    bass_z = zscore_normalize(bass_energy)

    beat_rms = np.array([_sample_feature(rms_t, rms_z, float(t)) for t in beat_times])
    beat_onset = np.array([_sample_feature(onset_t, onset_z, float(t)) for t in beat_times])
    beat_centroid = np.array([_sample_feature(centroid_t, centroid_z, float(t)) for t in beat_times])
    beat_bass = np.array([_sample_feature(bass_t, bass_z, float(t)) for t in beat_times])
    beat_accent = 0.40 * beat_rms + 0.35 * beat_onset + 0.25 * beat_bass

    bar_offset = _infer_bar_offset(beat_accent, beat_bass)
    bar_starts = list(range(bar_offset, len(beat_times) - 1, 4))

    if not bar_starts:
        bar_starts = [0]

    bar_energy_values: list[float] = []
    bar_peak_values: list[float] = []
    bar_transition_values: list[float] = []
    last_bar_energy = 0.0

    for start_idx in bar_starts:
        idx = np.arange(start_idx, min(start_idx + 4, len(beat_times)))
        bar_energy = float(np.mean(beat_accent[idx]) + 0.20 * beat_accent[idx[0]] + 0.10 * beat_bass[idx[0]])
        bar_peak = float(np.max(beat_accent[idx]))
        transition = max(0.0, bar_energy - last_bar_energy) if bar_energy_values else 0.0
        bar_energy_values.append(bar_energy)
        bar_peak_values.append(bar_peak)
        bar_transition_values.append(transition)
        last_bar_energy = bar_energy

    bar_energy_arr = np.asarray(bar_energy_values, dtype=float)
    bar_peak_arr = np.asarray(bar_peak_values, dtype=float)
    bar_transition_arr = np.asarray(bar_transition_values, dtype=float)

    hi_energy = float(np.percentile(bar_energy_arr, 72))
    lo_energy = float(np.percentile(bar_energy_arr, 32))
    hi_peak = float(np.percentile(bar_peak_arr, 78))
    hi_transition = float(np.percentile(bar_transition_arr, 80))

    section_labels = [
        classify_section(energy, peak, transition, hi_energy=hi_energy, lo_energy=lo_energy, hi_peak=hi_peak, hi_transition=hi_transition)
        for energy, peak, transition in zip(bar_energy_arr, bar_peak_arr, bar_transition_arr)
    ]
    section_labels = _smooth_section_labels(section_labels)

    phrase_energy = np.asarray([
        float(np.mean(bar_energy_arr[i:i + 4]))
        for i in range(0, len(bar_energy_arr), 4)
    ], dtype=float)
    phrase_jump = np.diff(np.r_[phrase_energy[:1], phrase_energy]) if len(phrase_energy) else np.asarray([], dtype=float)
    phrase_hi = float(np.percentile(phrase_energy, 75)) if len(phrase_energy) else 0.0
    jump_hi = float(np.percentile(phrase_jump, 80)) if len(phrase_jump) else 0.0
    accent_hi = float(np.percentile(bar_peak_arr, 88))
    transition_hi = float(np.percentile(bar_transition_arr, 82))

    events: list[dict] = [
        {'t': 0.00, 'kind': 'button', 'payload': 'Start'},
        {'t': 0.15, 'kind': 'joystick', 'payload': [0, 0]},
    ]
    last_button_t = -999.0

    for bar_i, start_idx in enumerate(bar_starts):
        if start_idx >= len(beat_times) - 1:
            break

        t = float(beat_times[start_idx])
        phrase_i = bar_i // 4
        phrase_energy_i = float(phrase_energy[phrase_i]) if phrase_i < len(phrase_energy) else 0.0
        phrase_jump_i = float(phrase_jump[phrase_i]) if phrase_i < len(phrase_jump) else 0.0

        if bar_i % 4 == 0 and phrase_energy_i >= phrase_hi and (t - last_button_t) > 4.0:
            label = 'Y' if phrase_jump_i >= jump_hi else 'Z'
            events.append({'t': round(t, 3), 'kind': 'button', 'payload': label})
            last_button_t = t
        elif bar_peak_arr[bar_i] >= accent_hi and section_labels[bar_i] != 'low' and (t - last_button_t) > 2.5:
            events.append({'t': round(t, 3), 'kind': 'button', 'payload': 'B'})
            last_button_t = t

        next_transition = float(bar_transition_arr[bar_i + 1]) if (bar_i + 1) < len(bar_transition_arr) else 0.0
        if bar_i % 4 == 3 and next_transition >= transition_hi:
            fill_idx = min(start_idx + 3, len(beat_times) - 2)
            fill_t = float(beat_times[fill_idx])
            if (fill_t - last_button_t) > 2.0:
                events.append({'t': round(fill_t, 3), 'kind': 'button', 'payload': 'X'})
                last_button_t = fill_t

        _emit_bar_pattern(events, beat_times, start_idx, section_labels[bar_i], beat_accent, beat_centroid, phrase_i)

    events.append({'t': round(duration + 0.10, 3), 'kind': 'joystick', 'payload': [0, 0]})
    events.append({'t': round(duration + 0.20, 3), 'kind': 'button', 'payload': 'Stop'})
    events.sort(key=lambda e: float(e['t']))
    compact = _compact_events(events)

    app.logger.info(
        'Generated %s dance events for %s (tempo=%.2f, bars=%s, bar_offset=%s)',
        len(compact),
        audio_path,
        tempo,
        len(bar_starts),
        bar_offset,
    )

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


def _format_robot_network_error(err: BaseException) -> str:
    reason = getattr(err, 'reason', err)
    if isinstance(reason, TimeoutError):
        return 'timed out'
    if isinstance(reason, socket.timeout):
        return 'timed out'
    if isinstance(reason, OSError):
        if getattr(reason, 'errno', None) == 51:
            return 'network is unreachable'
        return reason.strerror or str(reason)
    return str(reason)


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
            app.logger.debug('Dispatch joystick event t=%.3f x=%s y=%s to %s', float(event['t']), int(x), int(y), base_url)
            status = _http_robot_get(base_url, '/joystick', {'x': int(x), 'y': int(y)})
            dispatches.append({'t': event['t'], 'kind': 'joystick', 'payload': [int(x), int(y)], 'status': status})
        else:
            label = str(event['payload'])
            app.logger.debug('Dispatch button event t=%.3f label=%s to %s', float(event['t']), label, base_url)
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
    app.logger.info('Analyze request received for file: %s', filename)
    suffix = Path(filename).suffix or '.mp3'
    if suffix.lower() not in ALLOWED_AUDIO_SUFFIXES:
        return _error_response('Unsupported audio format. Allowed: mp3, wav, ogg, m4a, flac.', 400, code='unsupported_audio_format')

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            upload.save(temp_file)
            temp_path = temp_file.name

        events, tempo, duration = build_events(temp_path)
        app.logger.info('Analyze complete for %s: tempo=%.2f duration=%.3f event_count=%s', filename, tempo, duration, len(events))
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
    app.logger.info('Send-to-robot request: base_url=%s dry_run=%s', base_url, dry_run)
    try:
        events = _validate_robot_events(_with_safe_bookends(payload.get('events')))
        send_speed = _validate_send_speed(payload.get('send_speed'))
    except (TypeError, ValueError) as err:
        return _error_response(f'Invalid robot send request: {err}', 400, code='invalid_robot_send_request')

    if dry_run:
        app.logger.debug('Dry-run validated %s events at speed %.2f', len(events), send_speed)
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
            detail = _format_robot_network_error(err)
            app.logger.warning('Robot dispatch network timeout to %s: %s', base_url, detail)
            return _error_response(
                f'Could not reach robot at {base_url}. Check Wi-Fi and power.',
                502,
                code='robot_unreachable',
                details=detail,
            )
        future.cancel()
        app.logger.warning('Robot dispatch timed out for %s events to %s', len(events), base_url)
        return _error_response('Robot dispatch timed out.', 504, code='robot_dispatch_timeout', details=f'Timeline execution exceeded {ROBOT_MAX_SCRIPT_SECONDS + 15.0:.0f}s timeout.')
    except URLError as err:
        detail = _format_robot_network_error(err)
        app.logger.warning('Robot dispatch network error to %s: %s', base_url, detail)
        return _error_response(
            f'Could not reach robot at {base_url}. Check Wi-Fi and power.',
            502,
            code='robot_unreachable',
            details=detail,
        )
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
