#!/usr/bin/env bash
set -euo pipefail
export COMFY_PORT="${COMFY_PORT:-8188}"
export WORKDIR="/workspace"
export COMFY_DIR="$WORKDIR/ComfyUI"
export MODELS_DIR="${MODELS_DIR:-$WORKDIR/models}"

echo "[*] Preparing environment..."
apt-get update -y && apt-get install -y git aria2 curl jq >/dev/null || true
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

mkdir -p "$MODELS_DIR" "$COMFY_DIR/custom_nodes"

if [ ! -d "$COMFY_DIR/.git" ]; then
  git clone --depth=1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY_DIR"
fi

if [ -f comfyui_nodes.txt ]; then
  while read -r repo; do
    [ -z "$repo" ] && continue
    case "$repo" in \#*) continue;; esac
    name="$(basename "$repo" .git)"
    [ -d "$COMFY_DIR/custom_nodes/$name" ] || git clone --depth=1 "$repo" "$COMFY_DIR/custom_nodes/$name" || true
  done < comfyui_nodes.txt
fi

ln -sfn "$MODELS_DIR" "$COMFY_DIR/models"
python "$COMFY_DIR/main.py" --listen 0.0.0.0 --port "$COMFY_PORT" --enable-cors &

for i in {1..90}; do
  curl -sf "http://127.0.0.1:$COMFY_PORT/system_stats" >/dev/null && break || sleep 1
done

python worker.py
