"""MCP adapter for a running, local Kame32 Flask app. No hardware calls on startup."""
import argparse
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

API_URL = os.getenv('KAME32_APP_URL', 'http://127.0.0.1:5000').rstrip('/')
origin = urlsplit(API_URL)
trusted_hosts = {'127.0.0.1', 'localhost', '::1'} | {host.strip().lower() for host in os.getenv('KAME32_TRUSTED_APP_HOSTS', '').split(',') if host.strip()}
if origin.scheme not in {'http', 'https'} or origin.hostname not in trusted_hosts or origin.username or origin.password or origin.path or origin.query or origin.fragment:
    raise ValueError('KAME32_APP_URL must be an HTTP(S) origin on loopback or an explicitly configured trusted app host.')
AUDIO_DIR = Path(os.getenv('KAME32_AUDIO_DIR', str(Path(__file__).parent))).resolve()

mcp = FastMCP('Kame32 DanceMode & TeachMoves', host='127.0.0.1', port=8000,
    instructions='Control a running local Flask app. Browser actions require a connected tab and return a command id: inspect its status before claiming completion. Servo keyframes require the upgraded pose/watchdog firmware for hardware playback. Live robot dispatch physically moves hardware and must be explicitly requested. Never infer live dispatch from a preview request.')
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


def api(method, path, *, timeout=30, **kwargs):
    try:
        with httpx.Client(base_url=API_URL, trust_env=False, timeout=timeout) as client:
            response = client.request(method, path, **kwargs)
        if response.is_error:
            try:
                message = response.json().get('error', f'HTTP {response.status_code}')
            except ValueError:
                message = f'HTTP {response.status_code}'
            raise ValueError(message)
        return response.json()
    except httpx.RequestError as error:
        raise ValueError('Local app request failed. Check Flask is running and inspect its logs before retrying a live dispatch.') from error


@mcp.tool(annotations=READ)
def get_status() -> dict:
    """Get connected browser tabs, configured app address, and feature limits."""
    return {'app_url': API_URL, 'clients': api('GET', '/api/browser-clients'),
            'robot': api('GET', '/api/robot/status'),
            'move_slots': [f'Move{i}' for i in range(1, 7)], 'recording_limit_seconds': 60,
            'keyframes_hardware_supported': True, 'required_firmware_features': ['pose', 'watchdog', 'lease_token']}


@mcp.tool(annotations=READ)
def get_presets() -> dict:
    """Read built-in dance timelines and keyframe routines."""
    return api('GET', '/api/presets')


@mcp.tool(annotations=WRITE)
def analyze_audio(path: str) -> dict:
    """Analyze a local audio file under KAME32_AUDIO_DIR (default repository directory). Returns dance events, tempo and duration; does not dispatch."""
    file = (AUDIO_DIR / path).resolve()
    if not file.is_relative_to(AUDIO_DIR) or not file.is_file():
        raise ValueError('Audio must be an existing file under KAME32_AUDIO_DIR.')
    if file.suffix.lower() not in {'.mp3', '.wav', '.ogg', '.m4a', '.flac'} or file.stat().st_size > 49 * 1024 * 1024:
        raise ValueError('Use a supported audio file no larger than 49 MiB.')
    with file.open('rb') as audio:
        return api('POST', '/api/analyze-audio', files={'audio': (file.name, audio)}, timeout=300)


@mcp.tool(annotations=READ)
def validate_timeline(events: list[dict], send_speed: float = 1.0, base_url: str | None = None) -> dict:
    """Validate robot events and safety boundaries without sending commands to hardware."""
    return api('POST', '/api/send-to-robot', json={'events': events, 'send_speed': send_speed, 'base_url': base_url, 'dry_run': True})


@mcp.tool(annotations=DESTRUCTIVE)
def dispatch_robot(events: list[dict], base_url: str = 'http://192.168.4.1', send_speed: float = 1.0) -> dict:
    """LIVE HARDWARE: send a timeline to a configured robot origin. Physically moves the robot. Use only on explicit user instruction; validate first. Never retry automatically after an uncertain response. Requires the app's origin allowlist; pose events require upgraded watchdog firmware."""
    return api('POST', '/api/send-to-robot', timeout=2450,
               json={'events': events, 'base_url': base_url, 'send_speed': send_speed, 'dry_run': False})


@mcp.tool(annotations=DESTRUCTIVE)
def cancel_robot_dispatch() -> dict:
    """Request cooperative cancellation of the app's active robot timeline. Worker attempts neutral/Stop, but network loss can prevent delivery. Returns requested status, not a hardware-stop guarantee. Poll get_status until inactive. Does not stop independently initiated robot motion."""
    return api('POST', '/api/robot/cancel')


@mcp.tool(annotations=READ)
def list_moves() -> dict:
    """List server-persisted TeachMoves keyframes, shared with browser tabs."""
    return api('GET', '/api/moves')


MoveName = Literal['Move1', 'Move2', 'Move3', 'Move4', 'Move5', 'Move6']


@mcp.tool(annotations=READ)
def get_move(name: MoveName) -> dict:
    """Read a saved move's complete servo keyframes."""
    return api('GET', f'/api/moves/{name}')


@mcp.tool(annotations=DESTRUCTIVE)
def save_move(name: MoveName, frames: list[dict], events: list[dict] | None = None) -> dict:
    """Create or replace a saved TeachMoves slot. Frames start at t=0, last at most 60 seconds, and contain poses s0–s7 in degrees (0–180). Optional events attach a stock joystick/button recording; servo-only hardware playback requires upgraded firmware."""
    return api('PUT', f'/api/moves/{name}', json={'frames': frames, 'events': events})


@mcp.tool(annotations=READ)
def validate_move(name: MoveName, send_speed: float = 1.0, playback_mode: Literal['auto', 'stock', 'pose'] = 'auto') -> dict:
    """Dry-run a saved servo move. Validates frames and boundaries; does not probe or move hardware."""
    return api('POST', f'/api/moves/{name}/send', json={'dry_run': True, 'send_speed': send_speed, 'playback_mode': playback_mode})


@mcp.tool(annotations=DESTRUCTIVE)
def dispatch_move(name: MoveName, base_url: str = 'http://192.168.4.1', send_speed: float = 1.0, playback_mode: Literal['auto', 'stock', 'pose'] = 'auto') -> dict:
    """LIVE HARDWARE: stream a saved servo move. Auto prefers updated pose firmware and falls back to recorded stock commands when available. Stock mode requires joystick/button commands recorded with the move; pose mode requires updated firmware. Never approximates servo frames. Use only on explicit user instruction. Cancel with cancel_robot_dispatch."""
    return api('POST', f'/api/moves/{name}/send', timeout=300,
               json={'base_url': base_url, 'send_speed': send_speed, 'dry_run': False, 'playback_mode': playback_mode})


@mcp.tool(annotations=DESTRUCTIVE)
def delete_move(name: MoveName) -> dict:
    """Delete a saved TeachMoves slot."""
    return api('DELETE', f'/api/moves/{name}')


@mcp.tool(annotations=DESTRUCTIVE)
def control_browser(client_id: str, action: Literal['get_state', 'set_mode', 'set_pose', 'set_joystick', 'button', 'load_events', 'load_move', 'play', 'pause', 'reset', 'record', 'stop_recording', 'select_move'], arguments: dict | None = None) -> dict:
    """Queue a PREVIEW-ONLY action for a connected tab. get_state returns the full preview state as its command result. Arguments: set_mode {mode}; set_pose {pose:{s0:90,...,s7:90}}; set_joystick {x,y}; button {label}; load_events {events}; load_move/select_move {name:'Move1'}; others {}. record/stop_recording/select_move require TeachMoves. record replaces the selected slot upon stop. Acknowledgment is asynchronous: inspect get_browser_command. Commands expire after 30s; never report queued as completed."""
    return api('POST', '/api/browser-commands', json={'client_id': client_id, 'action': action, 'arguments': arguments or {}})


@mcp.tool(annotations=READ)
def get_browser_command(command_id: str) -> dict:
    """Get queued/delivered/completed/failed/expired command status. History lasts five minutes; app restarts clear it."""
    # UUID validation prevents caller-supplied URL path traversal.
    import uuid
    ident = str(uuid.UUID(command_id))
    return api('GET', f'/api/browser-commands/{ident}')


@mcp.resource('kame32://status')
def status_resource() -> str:
    """Application connectivity and capabilities."""
    return json.dumps(get_status())


@mcp.resource('kame32://presets')
def presets_resource() -> str:
    """Built-in routines."""
    return json.dumps(get_presets())


@mcp.resource('kame32://moves/{name}')
def move_resource(name: str) -> str:
    """Saved move keyframes."""
    if name not in {f'Move{i}' for i in range(1, 7)}:
        raise ValueError('Invalid move name.')
    return json.dumps(get_move(name))


@mcp.prompt()
def teach_move(goal: str) -> str:
    """Plan a preview teaching session without live robot dispatch."""
    return f'User teaching goal: {goal}\nInspect get_status, choose a connected TeachMoves tab, select a slot, then record and adjust preview controls. Stop recording, verify each command acknowledgment, inspect get_move and preview the saved move. Ask before overwriting an existing slot if not already authorized. Do not dispatch hardware for this preview task.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport', choices=['stdio', 'streamable-http'], default='stdio')
    parser.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1', help='Use 0.0.0.0 only inside a container with loopback host port publishing.')
    args = parser.parse_args()
    mcp.settings.host = args.host
    mcp.run(transport=args.transport)
