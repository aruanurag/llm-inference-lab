#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
DTYPE="${DTYPE:-auto}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $PORT is already in use."
    echo "Stop the existing server first, then rerun this command."
    echo "Try: pkill -f \"vllm serve\""
    exit 1
  fi
fi

mkdir -p results/logs

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="results/logs/vllm-server-${TIMESTAMP}.log"
START_FILE="results/logs/server-start-${TIMESTAMP}.txt"

VLLM_COMMAND=(
  vllm
  serve
  "$MODEL"
  --host "$HOST"
  --port "$PORT"
  --dtype "$DTYPE"
)

if [[ -n "$MAX_MODEL_LEN" ]]; then
  VLLM_COMMAND+=(--max-model-len "$MAX_MODEL_LEN")
fi

if [[ -n "$MAX_NUM_SEQS" ]]; then
  VLLM_COMMAND+=(--max-num-seqs "$MAX_NUM_SEQS")
fi

if [[ -n "$MAX_NUM_BATCHED_TOKENS" ]]; then
  VLLM_COMMAND+=(--max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS")
fi

if [[ -n "$EXTRA_ARGS" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARGS_ARRAY=($EXTRA_ARGS)
  VLLM_COMMAND+=("${EXTRA_ARGS_ARRAY[@]}")
fi

echo "Starting vLLM OpenAI-compatible server"
echo "Model: $MODEL"
echo "URL: http://$HOST:$PORT"
echo "Dtype: $DTYPE"
echo "Max model length: ${MAX_MODEL_LEN:-default}"
echo "Max sequences: ${MAX_NUM_SEQS:-default}"
echo "Max batched tokens: ${MAX_NUM_BATCHED_TOKENS:-default}"
echo "Log: $LOG_FILE"

printf "Command:"
printf " %q" "${VLLM_COMMAND[@]}"
printf "\n"

{
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "model=$MODEL"
  echo "host=$HOST"
  echo "port=$PORT"
  echo "dtype=$DTYPE"
  echo "max_model_len=${MAX_MODEL_LEN:-default}"
  echo "max_num_seqs=${MAX_NUM_SEQS:-default}"
  echo "max_num_batched_tokens=${MAX_NUM_BATCHED_TOKENS:-default}"
  printf "command="
  printf " %q" "${VLLM_COMMAND[@]}"
  printf "\n"
} > "$START_FILE"

exec "${VLLM_COMMAND[@]}" 2>&1 | tee "$LOG_FILE"
