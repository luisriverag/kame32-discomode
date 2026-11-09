import { teaching } from './app.js';

const storageKey = 'kame32.teachMoves.v1';
const info = document.getElementById('macroInfo');
const record = document.getElementById('recordMacro');
const stop = document.getElementById('stopMacro');
const play = document.getElementById('playMacro');
const remove = document.getElementById('deleteMacro');
const use = document.getElementById('useMacro');
const validate = document.getElementById('validateMacro');
const send = document.getElementById('sendMacro');
let sending = false;
let moves = {};
let selected = 'Move1';
let timer = null;
let started = 0;
let frames = [];
let stockEvents = [];
let stockCompatible = true;
let lastStock = '';
let recordedEvents = null;
let storageWarning = '';
let saving = false;
async function request(path, options = {}) {
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Move request failed.');
  return value;
}
try {
  moves = await request('/api/moves');
  // Import legacy browser-only slots once, without replacing shared slots.
  if (!localStorage.getItem('kame32.movesMigrated')) {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    for (let i = 1; i <= 6; i++) {
      const name = `Move${i}`;
      if (!moves[name] && validFrames(saved?.[name])) {
        await request(`/api/moves/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames: saved[name] }) });
        moves[name] = saved[name];
      }
    }
    localStorage.setItem('kame32.movesMigrated', '1');
  }
} catch (error) { storageWarning = `Shared storage: ${error.message}`; }

function validFrames(value) {
  return Array.isArray(value) && value.length >= 2 && value.length <= 1202
    && value.every((frame, index) => Number.isFinite(frame.t) && frame.t >= 0 && frame.t <= 60
      && (!index || frame.t >= value[index - 1].t)
      && Array.from({ length: 8 }, (_, i) => frame.pose?.[`s${i}`]).every(v => Number.isFinite(v) && v >= 0 && v <= 180));
}

function render() {
  const recording = timer !== null;
  document.querySelectorAll('[data-move]').forEach(button => {
    const name = button.dataset.move;
    button.textContent = `${name}${moves[name] ? ' •' : ''}`;
    button.setAttribute('aria-pressed', String(name === selected));
    button.disabled = recording || saving;
  });
  record.disabled = recording || saving || sending;
  record.textContent = moves[selected] ? `Re-record ${selected}` : `Record ${selected}`;
  stop.disabled = !recording;
  validate.disabled = send.disabled = sending || recording || saving || !moves[selected];
  play.disabled = remove.disabled = use.disabled = recording || saving || !moves[selected];
  info.textContent = recording ? `Recording ${selected}… ${frames.at(-1).t.toFixed(1)} / 60s`
    : `${selected}: ${moves[selected] ? `${moves[selected].at(-1).t.toFixed(1)}s saved` : 'empty'}. ${storageWarning}`;
}

for (let i = 1; i <= 6; i++) {
  const button = document.createElement('button');
  button.dataset.move = `Move${i}`;
  button.addEventListener('click', () => { selected = button.dataset.move; render(); });
  document.getElementById('macroSlots').appendChild(button);
}

async function persist() {
  await request(`/api/moves/${selected}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frames: moves[selected], events: recordedEvents }),
  });
  storageWarning = '';
}

function sampleStock(t) {
  const command = teaching.stockCommand();
  if (!command) { stockCompatible = false; return; }
  const signature = JSON.stringify(command);
  if (signature !== lastStock) {
    const previous = stockEvents.at(-1);
    if (previous?.kind === 'button' && previous.payload === 'Stop' && !(command.kind === 'button' && command.payload === 'Stop')) {
      stockEvents.push({ t, kind: 'button', payload: 'Start' });
    }
    stockEvents.push({ t, kind: command.kind, payload: command.payload });
    lastStock = signature;
  }
}
function sample() {
  const t = Math.min(60, (performance.now() - started) / 1000);
  frames.push({ t, pose: teaching.pose() });
  sampleStock(t);
  if (t >= 60) finish();
  else render();
}
async function finish() {
  if (timer === null) return;
  clearInterval(timer);
  timer = null;
  const t = Math.min(60, (performance.now() - started) / 1000);
  frames.push({ t: Math.max(0.001, t), pose: teaching.pose() });
  sampleStock(Math.max(0.001, t));
  recordedEvents = stockCompatible ? [...stockEvents, { t: Math.max(0.001, t), kind: 'button', payload: 'Stop' }] : null;
  moves[selected] = frames;
  saving = true; render();
  try { await persist(); }
  catch (error) { storageWarning = `Move is not saved: ${error.message}`; }
  saving = false; render();
}
record.addEventListener('click', () => {
  teaching.manual();
  started = performance.now();
  stockEvents = []; stockCompatible = true; lastStock = '';
  sampleStock(0);
  frames = [{ t: 0, pose: teaching.pose() }];
  timer = setInterval(sample, 50);
  render();
});
stop.addEventListener('click', finish);
play.addEventListener('click', () => { teaching.play(moves[selected]); });
remove.addEventListener('click', async () => {
  const name = selected;
  try { await request(`/api/moves/${name}`, { method: 'DELETE' }); delete moves[name]; render(); }
  catch (error) { info.textContent = error.message; }
});
use.addEventListener('click', () => {
  try {
    sessionStorage.setItem('kame32.pendingMove', JSON.stringify(moves[selected]));
    window.location.assign('/');
  } catch { info.textContent = 'Browser storage is required to transfer a move to DanceMode.'; }
});
window.addEventListener('pagehide', () => {
  if (timer !== null) { clearInterval(timer); timer = null; }
});
teaching.manual();
render();

export async function teachAction(action, args) {
  if (action === 'select_move') {
    if (timer !== null || saving) throw new Error('Stop recording and wait for saving before switching slots.');
    if (!/^Move[1-6]$/.test(args.name)) throw new Error('Invalid move slot.');
    selected = args.name;
    render();
  } else if (action === 'record') {
    if (timer !== null || saving) throw new Error('Already recording or saving.');
    record.click();
  } else if (action === 'stop_recording') {
    if (timer === null) throw new Error('Not recording.');
    await finish();
    if (storageWarning) throw new Error(storageWarning);
  }
}
setInterval(async () => {
  if (timer !== null || saving || sending) return;
  try { moves = await request('/api/moves'); render(); } catch { /* Preserve the last known slots. */ }
}, 2000);

async function sendSelectedMove(dryRun) {
  const name = selected;
  sending = true; render();
  info.textContent = dryRun ? 'Validating move…' : 'Sending move to robot…';
  try {
    const result = await request(`/api/moves/${name}/send`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: document.getElementById('teachRobotOrigin').value, dry_run: dryRun, playback_mode: document.getElementById('teachPlaybackMode').value }) });
    info.textContent = dryRun ? `${name} validated. ${result.stock_compatible ? 'Stock-compatible commands available.' : 'Updated pose firmware required.'}` : `${name} sent in ${result.playback_mode} mode. ${result.watchdog_active ? 'Device watchdog active.' : 'Stock firmware: no device watchdog.'}`;
  } catch (error) { info.textContent = error.message; }
  finally {
    sending = false;
    const message = info.textContent; render(); info.textContent = message;
  }
}
validate.addEventListener('click', () => sendSelectedMove(true));
send.addEventListener('click', () => sendSelectedMove(false));
document.getElementById('cancelMacro').addEventListener('click', async () => {
  try {
    const result = await request('/api/robot/cancel', { method: 'POST' });
    info.textContent = result.cancellation_requested ? 'Cancellation requested. Hardware stop delivery is best effort.' : 'No active app dispatch.';
  } catch (error) { info.textContent = error.message; }
});
