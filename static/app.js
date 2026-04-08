
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js';
import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/controls/OrbitControls.js';

const sceneCanvas = document.getElementById('scene');
const statusBox = document.getElementById('statusBox');
const transportSlider = document.getElementById('transportSlider');
const timelineSlider = document.getElementById('timelineSlider');
const timeLabel = document.getElementById('timeLabel');
const durationLabel = document.getElementById('durationLabel');
const servoReadout = document.getElementById('servoReadout');

const playBtn = document.getElementById('playBtn');
const pauseBtn = document.getElementById('pauseBtn');
const resetBtn = document.getElementById('resetBtn');
const speedInput = document.getElementById('speed');
const speedPresetButtons = [...document.querySelectorAll('[data-speed-preset]')];
const modeSelect = document.getElementById('modeSelect');

const joyX = document.getElementById('joyX');
const joyY = document.getElementById('joyY');
const joyXValue = document.getElementById('joyXValue');
const joyYValue = document.getElementById('joyYValue');
const periodInput = document.getElementById('period');
const stepHeightInput = document.getElementById('stepHeight');
const legSpreadInput = document.getElementById('legSpread');
const bodyHeightInput = document.getElementById('bodyHeight');

const eventsJson = document.getElementById('eventsJson');
const keyframesJson = document.getElementById('keyframesJson');
const loadEventsBtn = document.getElementById('loadEventsBtn');
const demoEventsBtn = document.getElementById('demoEventsBtn');
const loadKeyframesBtn = document.getElementById('loadKeyframesBtn');
const demoKeyframesBtn = document.getElementById('demoKeyframesBtn');

const audioFile = document.getElementById('audioFile');
const analyzeAudioBtn = document.getElementById('analyzeAudioBtn');
const visualizeAudioBtn = document.getElementById('visualizeAudioBtn');
const clearAudioBtn = document.getElementById('clearAudioBtn');
const audioPreview = document.getElementById('audioPreview');
const audioMeta = document.getElementById('audioMeta');
const sendToRobotBtn = document.getElementById('sendToRobotBtn');
const workflowAnalyze = document.getElementById('workflowAnalyze');
const workflowVisualize = document.getElementById('workflowVisualize');
const workflowSend = document.getElementById('workflowSend');

const panels = {
  joystick: document.getElementById('joystickCard'),
  button: document.getElementById('buttonCard'),
  pose: document.getElementById('poseCard'),
  events: document.getElementById('eventsCard'),
  keyframes: document.getElementById('keyframesCard'),
};

const servoMeta = [
  { key: 's0', label: 's0 front-left hip', leg: 'fl', joint: 'hip' },
  { key: 's1', label: 's1 front-right hip', leg: 'fr', joint: 'hip' },
  { key: 's2', label: 's2 front-left knee', leg: 'fl', joint: 'knee' },
  { key: 's3', label: 's3 front-right knee', leg: 'fr', joint: 'knee' },
  { key: 's4', label: 's4 rear-right hip', leg: 'rr', joint: 'hip' },
  { key: 's5', label: 's5 rear-left hip', leg: 'rl', joint: 'hip' },
  { key: 's6', label: 's6 rear-left knee', leg: 'rl', joint: 'knee' },
  { key: 's7', label: 's7 rear-right knee', leg: 'rr', joint: 'knee' },
];

const legOrder = {
  fl: { hip: 's0', knee: 's2', mount: new THREE.Vector3(1.6, 0.0, 1.0), side: 1, front: 1 },
  fr: { hip: 's1', knee: 's3', mount: new THREE.Vector3(1.6, 0.0, -1.0), side: -1, front: 1 },
  rl: { hip: 's5', knee: 's6', mount: new THREE.Vector3(-1.6, 0.0, 1.0), side: 1, front: -1 },
  rr: { hip: 's4', knee: 's7', mount: new THREE.Vector3(-1.6, 0.0, -1.0), side: -1, front: -1 },
};

const homePose = {
  s0: 110,
  s1: 70,
  s2: 80,
  s3: 100,
  s4: 70,
  s5: 110,
  s6: 100,
  s7: 80,
};

const state = {
  mode: 'joystick',
  playing: true,
  time: 0,
  duration: 12,
  speed: 1,
  buttonRoutine: 'X',
  livePose: { ...homePose },
  joystick: { x: 0, y: 0, period: 450, stepHeight: 20, legSpread: 20, bodyHeight: 10 },
  presets: null,
  eventTimeline: [],
  keyframes: [{ t: 0, pose: { ...homePose } }, { t: 1, pose: { ...homePose } }],
  analyzedAudio: null,
  audioSyncEnabled: false,
  audioReady: false,
};

function setStatus(message) {
  statusBox.textContent = message;
}

function setWorkflowStage(stage) {
  const states = {
    analyze: { analyze: 'active', visualize: '', send: '' },
    visualize: { analyze: 'done', visualize: 'active', send: '' },
    send: { analyze: 'done', visualize: 'done', send: 'active' },
    complete: { analyze: 'done', visualize: 'done', send: 'done' },
  };
  const selected = states[stage] || states.analyze;
  const map = [
    [workflowAnalyze, selected.analyze],
    [workflowVisualize, selected.visualize],
    [workflowSend, selected.send],
  ];
  for (const [el, stateClass] of map) {
    if (!el) continue;
    el.classList.remove('active', 'done');
    if (stateClass) el.classList.add(stateClass);
  }
}

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function degSin(deg) {
  return Math.sin((deg * Math.PI) / 180);
}

function normalizePose(pose) {
  const out = { ...homePose };
  for (const meta of servoMeta) {
    if (pose && pose[meta.key] != null) out[meta.key] = Number(pose[meta.key]);
  }
  return out;
}

function interpolatePose(a, b, t) {
  const out = {};
  for (const meta of servoMeta) {
    out[meta.key] = lerp(a[meta.key], b[meta.key], t);
  }
  return out;
}

function usingAudioClock() {
  return state.mode === 'events' && state.audioSyncEnabled && Boolean(audioPreview.src) && !audioPreview.hidden;
}

function pauseAnyAudio() {
  if (!audioPreview.paused) {
    audioPreview.pause();
  }
}

function waitForAudioReady() {
  return new Promise((resolve, reject) => {
    if (!audioPreview.src) {
      reject(new Error('No audio source loaded.'));
      return;
    }

    if (audioPreview.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      state.audioReady = true;
      resolve();
      return;
    }

    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error('Timed out waiting for decoded audio.'));
    }, 8000);

    const onReady = () => {
      if (settled) return;
      settled = true;
      cleanup();
      state.audioReady = true;
      resolve();
    };

    const onError = () => {
      if (settled) return;
      settled = true;
      cleanup();
      const mediaError = audioPreview.error;
      reject(new Error(mediaError ? `Browser could not decode audio (code ${mediaError.code}).` : 'Browser could not decode audio.'));
    };

    const cleanup = () => {
      clearTimeout(timeout);
      audioPreview.removeEventListener('loadeddata', onReady);
      audioPreview.removeEventListener('canplay', onReady);
      audioPreview.removeEventListener('error', onError);
    };

    audioPreview.addEventListener('loadeddata', onReady, { once: true });
    audioPreview.addEventListener('canplay', onReady, { once: true });
    audioPreview.addEventListener('error', onError, { once: true });
    audioPreview.load();
  });
}

function formatSpeedValue(value) {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? `${rounded.toFixed(1)}` : `${rounded}`;
}

function updateSpeedPresetButtons() {
  for (const button of speedPresetButtons) {
    const preset = Number(button.dataset.speedPreset);
    const isActive = Math.abs(preset - state.speed) < 0.001;
    button.classList.toggle('active', isActive);
  }
}

function applyPlaybackSpeed(value, { announce = false } = {}) {
  const numeric = clamp(Number(value || 1), 0.25, 3);
  state.speed = numeric;
  speedInput.value = formatSpeedValue(numeric);

  if ('preservesPitch' in audioPreview) audioPreview.preservesPitch = true;
  if ('mozPreservesPitch' in audioPreview) audioPreview.mozPreservesPitch = true;
  if ('webkitPreservesPitch' in audioPreview) audioPreview.webkitPreservesPitch = true;
  if (audioPreview.src) audioPreview.playbackRate = numeric;

  updateSpeedPresetButtons();
  if (announce) {
    setStatus(`Playback speed set to ${Math.round(numeric * 100)}%.`);
  }
}

function buttonRoutinePose(label, t) {
  const s = { ...homePose };
  if (label === 'Stop' || label === 'Start') return s;

  const beat = (value, scale = 1) => Math.sin(value * Math.PI * 2 * scale);

  if (label === 'A') {
    const wave = beat(t / 1.2, 1.5);
    s.s0 += 10;
    s.s2 -= 8;
    s.s1 -= 14 * Math.max(0, wave);
    s.s3 += 18 * Math.max(0, wave);
    s.s4 -= 6;
    s.s5 += 8;
    return s;
  }

  if (label === 'B') {
    const phase = clamp(t / 0.8, 0, 1);
    const crouch = Math.sin(Math.min(phase, 0.55) / 0.55 * Math.PI);
    const kick = phase > 0.55 ? Math.sin((phase - 0.55) / 0.45 * Math.PI) : 0;
    for (const key of ['s2', 's7']) s[key] -= 18 * crouch;
    for (const key of ['s3', 's6']) s[key] += 18 * crouch;
    for (const key of ['s0', 's5']) s[key] += 8 * crouch;
    for (const key of ['s1', 's4']) s[key] -= 8 * crouch;
    for (const key of ['s2', 's3', 's6', 's7']) s[key] += 26 * kick;
    return s;
  }

  if (label === 'X') {
    const swing = beat(t / 1.4, 1.2);
    const bounce = beat(t / 1.4, 2.4);
    s.s0 += 20 * swing;
    s.s5 += 20 * swing;
    s.s1 -= 20 * swing;
    s.s4 -= 20 * swing;
    s.s2 -= 8 * bounce;
    s.s7 -= 8 * bounce;
    s.s3 += 8 * bounce;
    s.s6 += 8 * bounce;
    return s;
  }

  if (label === 'Y') {
    const slide = beat(t / 2.2, 1.0);
    s.s0 += 12 * slide;
    s.s1 += 6 * slide;
    s.s5 -= 12 * slide;
    s.s4 -= 6 * slide;
    s.s2 -= 5 * Math.cos(t * 5);
    s.s3 += 5 * Math.cos(t * 5 + 1);
    s.s6 += 5 * Math.cos(t * 5 + 2.2);
    s.s7 -= 5 * Math.cos(t * 5 + 3.1);
    return s;
  }

  if (label === 'Z') {
    const frontBack = beat(t / 1.2, 1.0);
    s.s0 += 14 * frontBack;
    s.s1 -= 14 * frontBack;
    s.s5 += 14 * frontBack;
    s.s4 -= 14 * frontBack;
    s.s2 -= 8 * frontBack;
    s.s3 += 8 * frontBack;
    s.s6 += 8 * frontBack;
    s.s7 -= 8 * frontBack;
    return s;
  }

  return s;
}

function poseFromJoystick(timeSec) {
  const { x, y, period, stepHeight, legSpread, bodyHeight } = state.joystick;
  const absX = Math.abs(x);
  const absY = Math.abs(y);
  if (absX < 0.01 && absY < 0.01) {
    return normalizePose(homePose);
  }

  const phaseLinear = [90, 90, 270, 90, 270, 270, 90, 270];
  const phaseAngular = [90, 270, 270, 90, 270, 90, 90, 270];
  const progress = ((timeSec * 1000) / period) * 360;
  const linear = absY >= absX;
  const phaseBase = linear ? phaseLinear : phaseAngular;
  const stepAmplitude = (linear ? y : x) * 0.25;
  const bodyShift = linear ? stepAmplitude * 0.8 : 0.0;

  const offsets = {
    s0: 90 + legSpread - bodyShift,
    s1: 90 - legSpread + bodyShift,
    s4: 90 - legSpread - bodyShift,
    s5: 90 + legSpread + bodyShift,
    s2: 90 - bodyHeight,
    s3: 90 + bodyHeight,
    s6: 90 + bodyHeight,
    s7: 90 - bodyHeight,
  };

  const amplitudes = {
    s0: stepAmplitude,
    s1: stepAmplitude,
    s4: stepAmplitude,
    s5: stepAmplitude,
    s2: stepHeight,
    s3: stepHeight,
    s6: stepHeight,
    s7: stepHeight,
  };

  const phases = {
    s0: phaseBase[0] + progress,
    s1: phaseBase[1] + progress,
    s2: phaseBase[2] + 2 * progress,
    s3: phaseBase[3] + 2 * progress,
    s4: phaseBase[4] + progress,
    s5: phaseBase[5] + progress,
    s6: phaseBase[6] + 2 * progress,
    s7: phaseBase[7] + 2 * progress,
  };

  const pose = {};
  for (const meta of servoMeta) {
    pose[meta.key] = offsets[meta.key] + amplitudes[meta.key] * degSin(phases[meta.key]);
  }
  return pose;
}

function poseFromKeyframes(timeSec) {
  const frames = state.keyframes;
  if (!frames.length) return normalizePose(homePose);
  if (timeSec <= frames[0].t) return normalizePose(frames[0].pose);
  if (timeSec >= frames[frames.length - 1].t) return normalizePose(frames[frames.length - 1].pose);
  for (let i = 0; i < frames.length - 1; i += 1) {
    const a = frames[i];
    const b = frames[i + 1];
    if (timeSec >= a.t && timeSec <= b.t) {
      const t = (timeSec - a.t) / Math.max(0.0001, b.t - a.t);
      return interpolatePose(normalizePose(a.pose), normalizePose(b.pose), t);
    }
  }
  return normalizePose(homePose);
}

function parseButtonDuration(label) {
  return ({ A: 1.2, B: 0.8, X: 1.4, Y: 2.2, Z: 1.2, Start: 0.2, Stop: 0.2 }[label] ?? 1.0);
}

function poseFromEvents(timeSec) {
  const events = state.eventTimeline;
  if (!events.length) return normalizePose(homePose);

  let joystickState = { x: 0, y: 0 };
  let currentPose = normalizePose(homePose);
  let activeButton = null;
  let buttonStart = 0;

  for (const event of events) {
    if (event.t > timeSec) break;
    if (event.kind === 'joystick' && Array.isArray(event.payload)) {
      joystickState = { x: Number(event.payload[0]), y: Number(event.payload[1]) };
      activeButton = null;
    } else if (event.kind === 'button') {
      const label = String(event.payload);
      if (label === 'Stop' || label === 'Start') {
        activeButton = null;
        if (label === 'Stop') joystickState = { x: 0, y: 0 };
      } else {
        activeButton = label;
        buttonStart = event.t;
      }
    } else if ((event.kind === 'pose' || event.type === 'pose') && event.pose) {
      currentPose = normalizePose(event.pose);
      activeButton = null;
    }
  }

  if (activeButton) {
    const duration = parseButtonDuration(activeButton);
    const localT = clamp(timeSec - buttonStart, 0, duration);
    return buttonRoutinePose(activeButton, localT);
  }

  if (events.some((e) => (e.kind === 'pose' || e.type === 'pose') && e.pose)) {
    const poseEvents = events
      .filter((e) => (e.kind === 'pose' || e.type === 'pose') && e.pose)
      .map((e) => ({ t: Number(e.t), pose: normalizePose(e.pose) }));
    if (poseEvents.length) {
      const original = state.keyframes;
      state.keyframes = poseEvents;
      const result = poseFromKeyframes(timeSec);
      state.keyframes = original;
      return result;
    }
  }

  const previous = { ...state.joystick };
  state.joystick.x = joystickState.x;
  state.joystick.y = joystickState.y;
  const result = poseFromJoystick(timeSec);
  state.joystick.x = previous.x;
  state.joystick.y = previous.y;
  return result || currentPose;
}

function poseForCurrentMode() {
  if (state.mode === 'pose') return normalizePose(state.livePose);
  if (state.mode === 'button') return buttonRoutinePose(state.buttonRoutine, state.time);
  if (state.mode === 'events') return poseFromEvents(state.time);
  if (state.mode === 'keyframes') return poseFromKeyframes(state.time);
  return poseFromJoystick(state.time);
}

const renderer = new THREE.WebGLRenderer({ canvas: sceneCanvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(sceneCanvas.clientWidth, sceneCanvas.clientHeight, false);

const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x0b0f14, 12, 30);

const camera = new THREE.PerspectiveCamera(45, sceneCanvas.clientWidth / sceneCanvas.clientHeight, 0.1, 100);
camera.position.set(6.4, 4.6, 7.5);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.8, 0);
controls.enableDamping = true;

const hemi = new THREE.HemisphereLight(0xffffff, 0x223344, 1.5);
scene.add(hemi);
const dir = new THREE.DirectionalLight(0xffffff, 1.2);
dir.position.set(4, 8, 6);
scene.add(dir);

const ground = new THREE.Mesh(
  new THREE.CircleGeometry(10, 64),
  new THREE.MeshStandardMaterial({ color: 0x17202a, roughness: 0.92, metalness: 0.05 })
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -2.25;
scene.add(ground);

const grid = new THREE.GridHelper(18, 36, 0x334155, 0x1f2937);
grid.position.y = -2.24;
scene.add(grid);

const robotGroup = new THREE.Group();
scene.add(robotGroup);

const body = new THREE.Mesh(
  new THREE.BoxGeometry(4.0, 1.0, 2.4),
  new THREE.MeshStandardMaterial({ color: 0x60a5fa, roughness: 0.55, metalness: 0.15 })
);
body.position.y = 0.65;
robotGroup.add(body);

const topShell = new THREE.Mesh(
  new THREE.BoxGeometry(2.1, 0.35, 1.6),
  new THREE.MeshStandardMaterial({ color: 0xdbeafe, roughness: 0.45, metalness: 0.08 })
);
topShell.position.set(0, 1.2, 0);
robotGroup.add(topShell);

const legMeshes = {};
const upperLen = 1.3;
const lowerLen = 1.3;

for (const [legName, def] of Object.entries(legOrder)) {
  const legRoot = new THREE.Group();
  legRoot.position.copy(def.mount);
  legRoot.position.y = 0.25;
  body.add(legRoot);

  const hipPivot = new THREE.Group();
  legRoot.add(hipPivot);

  const upper = new THREE.Mesh(
    new THREE.BoxGeometry(0.34, upperLen, 0.34),
    new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.45, metalness: 0.1 })
  );
  upper.position.y = -upperLen / 2;
  hipPivot.add(upper);

  const kneePivot = new THREE.Group();
  kneePivot.position.y = -upperLen;
  hipPivot.add(kneePivot);

  const lower = new THREE.Mesh(
    new THREE.BoxGeometry(0.26, lowerLen, 0.26),
    new THREE.MeshStandardMaterial({ color: 0xcbd5e1, roughness: 0.45, metalness: 0.08 })
  );
  lower.position.y = -lowerLen / 2;
  kneePivot.add(lower);

  const foot = new THREE.Mesh(
    new THREE.SphereGeometry(0.16, 16, 16),
    new THREE.MeshStandardMaterial({ color: 0x94a3b8, roughness: 0.6, metalness: 0.1 })
  );
  foot.position.y = -lowerLen;
  kneePivot.add(foot);

  legMeshes[legName] = { legRoot, hipPivot, kneePivot, foot, side: def.side, front: def.front };
}

function updateRobotPose(pose) {
  const normalized = normalizePose(pose);

  const leftAvg = (normalized.s0 + normalized.s5) / 2;
  const rightAvg = (normalized.s1 + normalized.s4) / 2;
  const frontAvg = (normalized.s0 + normalized.s1) / 2;
  const rearAvg = (normalized.s4 + normalized.s5) / 2;
  const kneeAvg = (normalized.s2 + normalized.s3 + normalized.s6 + normalized.s7) / 4;

  robotGroup.position.y = lerp(-0.25, 0.55, clamp((100 - kneeAvg) / 35, 0.05, 0.95));
  robotGroup.rotation.z = THREE.MathUtils.degToRad((leftAvg - rightAvg) * 0.18);
  robotGroup.rotation.x = THREE.MathUtils.degToRad((rearAvg - frontAvg) * 0.12);
  body.rotation.y = THREE.MathUtils.degToRad((normalized.s0 - normalized.s1 + normalized.s5 - normalized.s4) * 0.04);

  for (const [legName, def] of Object.entries(legOrder)) {
    const hipKey = def.hip;
    const kneeKey = def.knee;
    const leg = legMeshes[legName];
    const hipAngle = normalized[hipKey];
    const kneeAngle = normalized[kneeKey];

    const hipPitch = (hipAngle - 90) * 0.55;
    const sideLift = (hipAngle - 90) * 0.12 * leg.side;
    const kneePitch = (kneeAngle - 90) * 0.78;

    leg.legRoot.rotation.z = THREE.MathUtils.degToRad(sideLift);
    leg.hipPivot.rotation.z = 0;
    leg.hipPivot.rotation.x = THREE.MathUtils.degToRad(hipPitch);
    leg.kneePivot.rotation.x = THREE.MathUtils.degToRad(kneePitch);
  }

  servoReadout.innerHTML = '';
  for (const meta of servoMeta) {
    const chip = document.createElement('div');
    chip.className = 'badge';
    chip.textContent = `${meta.key} ${normalized[meta.key].toFixed(0)}°`;
    servoReadout.appendChild(chip);
  }
}

function resizeRenderer() {
  const width = sceneCanvas.clientWidth;
  const height = sceneCanvas.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resizeRenderer);

function setDuration(value) {
  state.duration = Math.max(0.5, Number(value));
  transportSlider.max = state.duration;
  timelineSlider.max = state.duration;
  durationLabel.textContent = `Duration ${state.duration.toFixed(2)}s`;
}

function syncTransport() {
  transportSlider.value = state.time;
  timelineSlider.value = state.time;
  timeLabel.textContent = `${state.time.toFixed(2)}s`;
}

function applyModeVisibility() {
  for (const [key, panel] of Object.entries(panels)) {
    panel.hidden = key !== state.mode;
  }
}

function setMode(mode) {
  state.mode = mode;
  modeSelect.value = mode;
  applyModeVisibility();
  if (mode !== 'events') {
    state.audioSyncEnabled = false;
    pauseAnyAudio();
  }
  if (mode === 'button') setDuration(parseButtonDuration(state.buttonRoutine));
  if (mode === 'pose') setDuration(12);
  if (mode === 'joystick') setDuration(12);
  if (mode === 'events') {
    const last = state.eventTimeline[state.eventTimeline.length - 1];
    let duration = last ? Math.max(4, Number(last.t) + 0.5) : 12;
    if (state.audioSyncEnabled && state.analyzedAudio?.duration != null) {
      duration = Math.max(duration, Number(state.analyzedAudio.duration));
    }
    setDuration(duration);
  }
  if (mode === 'keyframes') {
    const last = state.keyframes[state.keyframes.length - 1];
    setDuration(last ? Math.max(1, Number(last.t)) : 12);
  }
  setStatus(`Mode: ${mode}`);
}

function buildServoSliders() {
  const container = document.getElementById('servoSliders');
  for (const meta of servoMeta) {
    const wrap = document.createElement('div');
    const label = document.createElement('label');
    label.textContent = meta.label;
    const input = document.createElement('input');
    input.type = 'range';
    input.min = 0;
    input.max = 180;
    input.step = 1;
    input.value = state.livePose[meta.key];
    const value = document.createElement('div');
    value.className = 'servo-value';
    value.textContent = `${state.livePose[meta.key]}°`;
    input.addEventListener('input', () => {
      state.livePose[meta.key] = Number(input.value);
      value.textContent = `${input.value}°`;
      if (state.mode === 'pose') updateRobotPose(state.livePose);
    });
    wrap.append(label, input, value);
    container.appendChild(wrap);
  }
}

function loadJsonIntoMode(kind, payload, options = {}) {
  if (kind === 'events') {
    state.eventTimeline = payload
      .map((e) => ({ ...e, t: Number(e.t ?? 0) }))
      .sort((a, b) => a.t - b.t);
    const last = state.eventTimeline[state.eventTimeline.length - 1];
    const duration = options.duration ?? (last ? Math.max(4, last.t + parseButtonDuration(last.payload || 'X')) : 12);
    setDuration(duration);
    state.audioSyncEnabled = Boolean(options.audioSync);
    setStatus(`Loaded ${state.eventTimeline.length} events.`);
    setMode('events');
    return;
  }
  state.keyframes = payload
    .map((f) => ({ t: Number(f.t ?? 0), pose: normalizePose(f.pose) }))
    .sort((a, b) => a.t - b.t);
  const last = state.keyframes[state.keyframes.length - 1];
  setDuration(last ? Math.max(1, last.t) : 12);
  setStatus(`Loaded ${state.keyframes.length} keyframes.`);
  setMode('keyframes');
}

function activateAnalyzedAudioTimeline({ resetTime = false } = {}) {
  if (!state.analyzedAudio || !Array.isArray(state.analyzedAudio.events) || !state.analyzedAudio.events.length) {
    throw new Error('Analyze an MP3 first.');
  }
  const analyzed = state.analyzedAudio;
  loadJsonIntoMode('events', analyzed.events, { duration: analyzed.duration, audioSync: true });
  modeSelect.value = 'events';
  if (resetTime) {
    state.time = 0;
    audioPreview.currentTime = 0;
  }
  setWorkflowStage('visualize');
}

async function analyzeSelectedAudio() {
  const file = audioFile.files?.[0];
  if (!file) {
    setStatus('Choose an MP3 or other audio file first.');
    return;
  }

  if (analyzeAudioBtn.disabled) return;
  analyzeAudioBtn.disabled = true;

  if (audioPreview.dataset.objectUrl) {
    URL.revokeObjectURL(audioPreview.dataset.objectUrl);
  }
  const objectUrl = URL.createObjectURL(file);
  audioPreview.dataset.objectUrl = objectUrl;
  audioPreview.src = objectUrl;
  audioPreview.hidden = false;
  state.audioReady = false;
  audioMeta.textContent = `Analyzing ${file.name} ...`;
  setStatus('Uploading audio for beat analysis...');

  const formData = new FormData();
  formData.append('audio', file, file.name);

  try {
    const response = await fetch('/api/analyze-audio', { method: 'POST', body: formData });
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : { error: await response.text() };
    if (!response.ok) throw new Error(data.error || 'Analysis failed.');

    state.analyzedAudio = data;
    eventsJson.value = JSON.stringify(data.events, null, 2);
    activateAnalyzedAudioTimeline({ resetTime: true });
    await waitForAudioReady();
    applyPlaybackSpeed(state.speed);
    audioMeta.textContent = `${data.filename} · ${data.tempo.toFixed(1)} BPM · ${data.duration.toFixed(2)}s · ${data.event_count} events`;
    setStatus(`Audio analyzed: ${data.tempo.toFixed(1)} BPM, ${data.event_count} events loaded.`);
    setWorkflowStage('visualize');
  } catch (err) {
    state.analyzedAudio = null;
    state.audioSyncEnabled = false;
    state.audioReady = false;
    setWorkflowStage('analyze');
    setStatus(`Audio analysis failed: ${err.message}`);
    audioMeta.textContent = `Analysis failed for ${file.name}: ${err.message}`;
  } finally {
    analyzeAudioBtn.disabled = false;
  }
}

function clearAudioState() {
  pauseAnyAudio();
  state.analyzedAudio = null;
  state.audioSyncEnabled = false;
  state.audioReady = false;
  if (audioPreview.dataset.objectUrl) {
    URL.revokeObjectURL(audioPreview.dataset.objectUrl);
    delete audioPreview.dataset.objectUrl;
  }
  audioPreview.removeAttribute('src');
  audioPreview.hidden = true;
  audioFile.value = '';
  audioMeta.textContent = 'Choose an MP3, then the server will extract beats and load an event timeline for preview.';
  setWorkflowStage('analyze');
  setStatus('Audio cleared.');
}

playBtn.addEventListener('click', async () => {
  if (!usingAudioClock() && state.analyzedAudio?.events?.length) {
    activateAnalyzedAudioTimeline();
  }
  if (usingAudioClock()) {
    try {
      applyPlaybackSpeed(state.speed);
      if (!state.audioReady || audioPreview.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
        await waitForAudioReady();
      }
      await audioPreview.play();
      setWorkflowStage('send');
      setStatus('Playing audio-synced preview.');
      return;
    } catch (err) {
      setStatus(`Could not play audio: ${err.message}`);
      return;
    }
  }
  state.playing = true;
  setStatus('Playing.');
});

pauseBtn.addEventListener('click', () => {
  pauseAnyAudio();
  state.playing = false;
  setStatus('Paused.');
});

resetBtn.addEventListener('click', () => {
  pauseAnyAudio();
  if (audioPreview.src) audioPreview.currentTime = 0;
  state.time = 0;
  state.playing = false;
  syncTransport();
  setStatus('Reset to start.');
});

transportSlider.addEventListener('input', () => {
  state.time = Number(transportSlider.value);
  timelineSlider.value = transportSlider.value;
  state.playing = false;
  if (usingAudioClock()) audioPreview.currentTime = state.time;
  syncTransport();
});

timelineSlider.addEventListener('input', () => {
  state.time = Number(timelineSlider.value);
  transportSlider.value = timelineSlider.value;
  state.playing = false;
  if (usingAudioClock()) audioPreview.currentTime = state.time;
  syncTransport();
});

modeSelect.addEventListener('change', () => setMode(modeSelect.value));
speedInput.addEventListener('input', () => {
  applyPlaybackSpeed(speedInput.value);
});

for (const button of speedPresetButtons) {
  button.addEventListener('click', () => {
    applyPlaybackSpeed(button.dataset.speedPreset, { announce: true });
  });
}

joyX.addEventListener('input', () => {
  state.joystick.x = Number(joyX.value);
  joyXValue.textContent = joyX.value;
});
joyY.addEventListener('input', () => {
  state.joystick.y = Number(joyY.value);
  joyYValue.textContent = joyY.value;
});
periodInput.addEventListener('input', () => { state.joystick.period = Number(periodInput.value); });
stepHeightInput.addEventListener('input', () => { state.joystick.stepHeight = Number(stepHeightInput.value); });
legSpreadInput.addEventListener('input', () => { state.joystick.legSpread = Number(legSpreadInput.value); });
bodyHeightInput.addEventListener('input', () => { state.joystick.bodyHeight = Number(bodyHeightInput.value); });

for (const button of document.querySelectorAll('[data-button]')) {
  button.addEventListener('click', () => {
    pauseAnyAudio();
    state.buttonRoutine = button.dataset.button;
    state.time = 0;
    state.playing = true;
    setDuration(parseButtonDuration(state.buttonRoutine));
    setMode('button');
    modeSelect.value = 'button';
    setStatus(`Previewing button ${state.buttonRoutine}.`);
  });
}

loadEventsBtn.addEventListener('click', () => {
  try {
    const parsed = JSON.parse(eventsJson.value);
    if (!Array.isArray(parsed)) throw new Error('Expected an array of events.');
    pauseAnyAudio();
    loadJsonIntoMode('events', parsed, { audioSync: false });
    modeSelect.value = 'events';
    state.time = 0;
    setWorkflowStage('visualize');
  } catch (err) {
    setStatus(`Could not load events: ${err.message}`);
  }
});

demoEventsBtn.addEventListener('click', async () => {
  if (!state.presets) await fetchPresets();
  eventsJson.value = JSON.stringify(state.presets.mp3_style_demo, null, 2);
  state.audioSyncEnabled = false;
  setStatus('Loaded demo event JSON into the editor.');
});

loadKeyframesBtn.addEventListener('click', () => {
  try {
    const parsed = JSON.parse(keyframesJson.value);
    if (!Array.isArray(parsed)) throw new Error('Expected an array of keyframes.');
    pauseAnyAudio();
    loadJsonIntoMode('keyframes', parsed);
    modeSelect.value = 'keyframes';
    state.time = 0;
  } catch (err) {
    setStatus(`Could not load keyframes: ${err.message}`);
  }
});

demoKeyframesBtn.addEventListener('click', async () => {
  if (!state.presets) await fetchPresets();
  keyframesJson.value = JSON.stringify(state.presets.keyframe_groove[0].frames, null, 2);
  setStatus('Loaded demo keyframes into the editor.');
});

analyzeAudioBtn.addEventListener('click', analyzeSelectedAudio);
visualizeAudioBtn.addEventListener('click', () => {
  try {
    activateAnalyzedAudioTimeline({ resetTime: true });
    setStatus('Loaded analyzed dance in Event timeline mode.');
  } catch (err) {
    setStatus(err.message);
  }
});
clearAudioBtn.addEventListener('click', clearAudioState);
sendToRobotBtn.addEventListener('click', async () => {
  try {
    const parsed = JSON.parse(eventsJson.value);
    if (!Array.isArray(parsed) || parsed.length === 0) throw new Error('Load or generate an event timeline first.');
    await navigator.clipboard.writeText(JSON.stringify(parsed, null, 2));
    setWorkflowStage('complete');
    setStatus(`Copied ${parsed.length} events. Paste into your robot sender.`);
  } catch (err) {
    setStatus(`Could not copy robot script: ${err.message}`);
  }
});
audioFile.addEventListener('change', () => {
  const file = audioFile.files?.[0];
  if (file) {
    audioMeta.textContent = `${file.name} selected. Analyzing now...`;
    setStatus(`Analyzing ${file.name}...`);
    analyzeSelectedAudio();
  }
});
audioPreview.addEventListener('ended', () => {
  state.playing = false;
  state.time = 0;
  syncTransport();
});
audioPreview.addEventListener('pause', () => {
  if (usingAudioClock()) state.playing = false;
});
audioPreview.addEventListener('play', () => {
  if (usingAudioClock()) state.playing = true;
});

async function fetchPresets() {
  const response = await fetch('/api/presets');
  state.presets = await response.json();
}

buildServoSliders();
applyModeVisibility();
setDuration(12);
applyPlaybackSpeed(1);
setWorkflowStage('analyze');

let lastFrame = performance.now();
function animate(now) {
  requestAnimationFrame(animate);
  const deltaSec = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;

  if (usingAudioClock()) {
    state.time = Math.min(state.duration, audioPreview.currentTime || 0);
    state.playing = !audioPreview.paused;
  } else if (state.playing) {
    state.time += deltaSec * state.speed;
    if (state.time > state.duration) state.time = 0;
  }

  const pose = poseForCurrentMode();
  updateRobotPose(pose);
  syncTransport();
  controls.update();
  renderer.render(scene, camera);
}

Promise.all([fetchPresets()])
  .then(() => {
    eventsJson.value = JSON.stringify(state.presets.mp3_style_demo, null, 2);
    keyframesJson.value = JSON.stringify(state.presets.keyframe_groove[0].frames, null, 2);
    setStatus('Ready. Demo presets loaded.');
  })
  .catch((err) => setStatus(`Preset load failed: ${err.message}`));

resizeRenderer();
requestAnimationFrame((now) => {
  lastFrame = now;
  animate(now);
});

window.__kameAppReady = true;
