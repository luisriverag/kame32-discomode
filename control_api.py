"""Shared move storage and bounded, acknowledged browser commands."""
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from flask import jsonify, request


def validate_frames(frames):
    if not isinstance(frames, list) or not 2 <= len(frames) <= 1202:
        raise ValueError('frames must contain 2–1202 keyframes.')
    previous = -1
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError('Each keyframe must be an object.')
        t, pose = frame.get('t'), frame.get('pose')
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not previous <= t <= 60:
            raise ValueError('Keyframe times must be finite, sorted, and between 0 and 60 seconds.')
        if previous == -1 and t != 0:
            raise ValueError('The first keyframe must start at zero.')
        previous = t
        if not isinstance(pose, dict) or set(pose) != {f's{i}' for i in range(8)}:
            raise ValueError('Each pose requires exactly s0 through s7.')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 180 for v in pose.values()):
            raise ValueError('Servo angles must be finite numbers from 0 to 180.')
    if previous <= 0:
        raise ValueError('The move must have positive duration.')
    return frames


def register_control_api(app, dispatch_payload, validate_events):
    lock = threading.Lock()
    clients, commands = {}, {}

    @contextmanager
    def db():
        path = Path(app.config.get('MOVES_DB', os.getenv('KAME32_MOVES_DB', str(Path(app.instance_path) / 'moves.sqlite3'))))
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE IF NOT EXISTS moves (name TEXT PRIMARY KEY, frames TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS move_commands (name TEXT PRIMARY KEY, events TEXT NOT NULL)')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def move_name(name):
        if name not in {f'Move{i}' for i in range(1, 7)}:
            raise ValueError('Move name must be Move1 through Move6.')

    def prune():
        now = time.monotonic()
        for name in list(clients):
            if now - clients[name]['seen'] > 10:
                del clients[name]
        for item in list(commands.values()):
            if item['status'] in {'queued', 'delivered'} and now - item['created'] > 30:
                item['status'] = 'expired'
        for key in list(commands):
            if now - commands[key]['created'] > 300:
                del commands[key]

    def bad(error, status=400):
        return jsonify(error=str(error)), status

    @app.get('/api/moves')
    def list_moves():
        with db() as connection:
            rows = connection.execute('SELECT name, frames FROM moves ORDER BY name').fetchall()
        return jsonify({name: json.loads(frames) for name, frames in rows})

    @app.post('/api/moves/<name>/send')
    def send_saved_move(name):
        try:
            move_name(name)
        except (TypeError, ValueError, OverflowError) as error:
            return bad(error)
        with db() as connection:
            row = connection.execute('SELECT frames, events FROM moves LEFT JOIN move_commands USING (name) WHERE name=?', (name,)).fetchone()
        if not row:
            return bad('Move not found.', 404)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return bad('Expected a JSON object.')
        mode = payload.get('playback_mode', 'auto')
        if mode not in ('auto', 'pose', 'stock'):
            return bad('playback_mode must be auto, pose, or stock.')
        stock = json.loads(row[1]) if row[1] else None
        if mode == 'stock' and stock is None:
            return bad('This move has no stock commands. Re-record using only joystick/button controls, or update the firmware for servo poses.')
        events = stock if mode == 'stock' else [{'t': frame['t'], 'kind': 'pose', 'payload': frame['pose']} for frame in validate_frames(json.loads(row[0]))]
        return dispatch_payload({'events': events, 'base_url': payload.get('base_url'),
                                 'send_speed': payload.get('send_speed'), 'dry_run': payload.get('dry_run', True),
                                 'stock_events': stock if mode == 'auto' else None})

    @app.route('/api/moves/<name>', methods=['GET', 'PUT', 'DELETE'])
    def saved_move(name):
        try:
            move_name(name)
            if request.method == 'PUT':
                payload = request.get_json(silent=True)
                frames = validate_frames(payload.get('frames') if isinstance(payload, dict) else None)
                stock = payload.get('events')
                if stock is not None:
                    stock = validate_events(stock)
                    if any(event['kind'] not in {'joystick', 'button'} or event['t'] > frames[-1]['t'] for event in stock):
                        raise ValueError('Stock commands must use joystick/button and fit within the recorded duration.')
                    stock = validate_events([*stock, {'t': frames[-1]['t'], 'kind': 'button', 'payload': 'Stop'}])
                with db() as connection:
                    connection.execute('INSERT OR REPLACE INTO moves VALUES (?, ?)', (name, json.dumps(frames)))
                    connection.execute('DELETE FROM move_commands WHERE name=?', (name,))
                    if stock is not None:
                        connection.execute('INSERT INTO move_commands VALUES (?, ?)', (name, json.dumps(stock)))
                return jsonify(name=name, frames=frames, events=stock, stock_compatible=stock is not None)
            with db() as connection:
                row = connection.execute('SELECT frames, events FROM moves LEFT JOIN move_commands USING (name) WHERE name=?', (name,)).fetchone()
                if not row:
                    return bad('Move not found.', 404)
                if request.method == 'DELETE':
                    connection.execute('DELETE FROM moves WHERE name=?', (name,))
                    connection.execute('DELETE FROM move_commands WHERE name=?', (name,))
                    return jsonify(deleted=name)
            return jsonify(name=name, frames=json.loads(row[0]), events=json.loads(row[1]) if row[1] else None, stock_compatible=row[1] is not None)
        except (TypeError, ValueError, OverflowError) as error:
            return bad(error)

    @app.route('/api/browser-clients', methods=['GET', 'POST'])
    def browser_clients():
        with lock:
            prune()
            if request.method == 'POST':
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or payload.get('page') not in {'DanceMode', 'TeachMoves'}:
                    return bad('Invalid browser registration.')
                ident = payload.get('client_id')
                if not isinstance(ident, str) or len(ident) > 80 or not ident:
                    return bad('Invalid client id.')
                if ident not in clients and len(clients) >= 32:
                    return bad('Too many connected clients.', 429)
                snapshot = payload.get('state', {})
                if not isinstance(snapshot, dict) or len(json.dumps(snapshot)) > 8192:
                    return bad('Invalid browser state.')
                clients[ident] = {'page': payload['page'], 'seen': time.monotonic(), 'state': snapshot}
            return jsonify([{'client_id': key, 'page': value['page'], 'state': value['state'], 'age_seconds': round(time.monotonic() - value['seen'], 2)} for key, value in clients.items()])

    @app.route('/api/browser-commands', methods=['POST', 'GET'])
    def browser_commands():
        with lock:
            prune()
            if request.method == 'GET':
                ident = request.args.get('client_id')
                if ident not in clients:
                    return bad('Browser is not registered.', 404)
                pending = [c for c in commands.values() if c['client_id'] == ident and c['status'] == 'queued']
                for item in pending:
                    item['status'] = 'delivered'
                return jsonify(pending)
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return bad('Command must be an object.')
            ident, action, args = payload.get('client_id'), payload.get('action'), payload.get('arguments', {})
            if not isinstance(ident, str) or ident not in clients:
                return bad('No connected browser with this client id.', 404)
            allowed = {'get_state', 'set_mode', 'set_pose', 'set_joystick', 'button', 'load_events', 'load_move', 'play', 'pause', 'reset', 'record', 'stop_recording', 'select_move'}
            if not isinstance(action, str) or action not in allowed or not isinstance(args, dict):
                return bad('Unknown action or invalid arguments.')
            if action in {'record', 'stop_recording', 'select_move'} and clients[ident]['page'] != 'TeachMoves':
                return bad('This action requires a TeachMoves tab.')
            if sum(c['status'] in {'queued', 'delivered'} for c in commands.values()) >= 64:
                return bad('Browser command queue is full.', 429)
            if len(commands) >= 512:
                return bad('Command history is full; retry after expiry.', 429)
            command_id = str(uuid.uuid4())
            item = {'id': command_id, 'client_id': ident, 'action': action, 'arguments': args,
                    'status': 'queued', 'created': time.monotonic()}
            commands[command_id] = item
            return jsonify(item), 202

    @app.route('/api/browser-commands/<command_id>', methods=['GET', 'POST'])
    def browser_command(command_id):
        with lock:
            prune()
            item = commands.get(command_id)
            if not item:
                return bad('Command not found.', 404)
            if request.method == 'POST':
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or payload.get('client_id') != item['client_id'] or payload.get('status') not in {'completed', 'failed'}:
                    return bad('Invalid command acknowledgment.')
                if item['status'] != 'delivered':
                    return bad('Command is no longer awaiting acknowledgment.', 409)
                result = payload.get('result', '')
                if len(json.dumps(result)) > 2 * 1024 * 1024:
                    return bad('Command result is too large.')
                item.update(status=payload['status'], result=result)
            return jsonify(item)
