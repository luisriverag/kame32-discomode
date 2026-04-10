#!/usr/bin/env bash
set -euo pipefail

# Vendor Three.js ESM modules into Flask static/ so the app can run without CDN access.
# Requires Node.js + npm.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

pushd "$TMP_DIR" >/dev/null
npm init -y >/dev/null 2>&1
npm install --silent three@0.164.1

mkdir -p "$ROOT_DIR/static/vendor/three/build"
mkdir -p "$ROOT_DIR/static/vendor/three/examples/jsm/controls"
cp node_modules/three/build/three.module.js "$ROOT_DIR/static/vendor/three/build/three.module.js"
cp node_modules/three/examples/jsm/controls/OrbitControls.js "$ROOT_DIR/static/vendor/three/examples/jsm/controls/OrbitControls.js"
ROOT_DIR="$ROOT_DIR" python - <<'PY'
import os
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
controls = root / "static/vendor/three/examples/jsm/controls/OrbitControls.js"
text = controls.read_text(encoding="utf-8")
text = text.replace("from 'three';", "from '../../../build/three.module.js';")
text = text.replace('from "three";', 'from "../../../build/three.module.js";')
controls.write_text(text, encoding="utf-8")
PY
popd >/dev/null

echo "Vendored Three.js modules into static/vendor/three/."
echo "Restart Flask and reload the browser to use local modules first."
