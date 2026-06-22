#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${1:-}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
CTX_SIZE="${CTX_SIZE:-4096}"
PARALLEL="${PARALLEL:-4}"
BATCH_SIZE="${BATCH_SIZE:-512}"
UBATCH_SIZE="${UBATCH_SIZE:-128}"
GPU_LAYERS="${GPU_LAYERS:-auto}"

if [[ -z "$MODEL_PATH" ]]; then
  echo "Usage: ./run.sh /path/to/model.gguf"
  exit 1
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "Model file not found: $MODEL_PATH"
  exit 1
fi

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $PORT is already in use."
    echo "Stop the existing server first, then rerun this command."
    echo "Try: pkill -f \"llama-server\""
    exit 1
  fi
fi

mkdir -p results/logs

LOG_FILE="results/logs/llama-server-$(date +%Y%m%d-%H%M%S).log"
START_FILE="results/logs/server-start-$(date +%Y%m%d-%H%M%S).txt"

echo "Starting llama-server"
echo "Model: $MODEL_PATH"
echo "URL: http://$HOST:$PORT"
echo "Context size: $CTX_SIZE"
echo "Parallel slots: $PARALLEL"
echo "Batch size: $BATCH_SIZE"
echo "Micro-batch size: $UBATCH_SIZE"
echo "GPU layers: $GPU_LAYERS"
echo "Log: $LOG_FILE"

LLAMA_COMMAND=(
  llama-server
  --model "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --ctx-size "$CTX_SIZE"
  --parallel "$PARALLEL"
  --batch-size "$BATCH_SIZE"
  --ubatch-size "$UBATCH_SIZE"
  --n-gpu-layers "$GPU_LAYERS"
)

printf "Command:"
printf " %q" "${LLAMA_COMMAND[@]}"
printf "\n"

{
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "model=$MODEL_PATH"
  echo "host=$HOST"
  echo "port=$PORT"
  echo "ctx_size=$CTX_SIZE"
  echo "parallel=$PARALLEL"
  echo "batch_size=$BATCH_SIZE"
  echo "ubatch_size=$UBATCH_SIZE"
  echo "gpu_layers=$GPU_LAYERS"
  printf "command="
  printf " %q" "${LLAMA_COMMAND[@]}"
  printf "\n"
} > "$START_FILE"

exec "${LLAMA_COMMAND[@]}" 2>&1 | tee "$LOG_FILE"
