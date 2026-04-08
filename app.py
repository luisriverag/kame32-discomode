
from __future__ import annotations

import logging
import os
import random
import tempfile
from pathlib import Path

import librosa
import numpy as np
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.logger.setLevel(logging.INFO)

ALLOWED_AUDIO_SUFFIXES = {'.mp3', '.wav', '.ogg', '.m4a', '.flac'}


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


def build_events(audio_path: str, seed: int = 7) -> tuple[list[dict], float, float]:
    rng = random.Random(seed)

    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo_raw, beat_frames = librosa.beat.beat_track(y=y, sr=sr, onset_envelope=onset_env, trim=False)
    tempo = float(np.atleast_1d(tempo_raw)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    if len(beat_times) < 4:
        raise ValueError('Could not detect enough beats in the uploaded audio to build a dance routine.')

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


@app.post('/api/analyze-audio')
def analyze_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file uploaded. Use form field name "audio".'}), 400

    upload = request.files['audio']
    if not upload or not upload.filename:
        return jsonify({'error': 'No file selected.'}), 400

    filename = secure_filename(upload.filename)
    suffix = Path(filename).suffix or '.mp3'
    if suffix.lower() not in ALLOWED_AUDIO_SUFFIXES:
        return jsonify({'error': 'Unsupported audio format. Allowed: mp3, wav, ogg, m4a, flac.'}), 400

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
    except Exception as exc:
        app.logger.exception('Audio analysis failed for upload %s', filename)
        return jsonify({'error': 'Audio analysis failed. Verify the file is a valid, non-corrupt audio clip.'}), 400
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', '').strip().lower() in {'1', 'true', 'yes'}
    app.run(debug=debug_mode, host='127.0.0.1', port=5000)
