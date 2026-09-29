#!/bin/bash
# Route check on an Apple silicon Mac.
# Installs Jeff (github.com/firelex/jeff), downloads the 0.8B model (about 1.7 GB, first run only),
# starts it locally with MLX and measures it.
#
#   bash run_on_mac.sh                                    # the Banking77 support routing test
#   bash run_on_mac.sh --data my.jsonl --question q.json  # your own labeled examples
#
# Extra arguments go straight to route_check.py. Set JEFF_MODEL=mstrasser/Jeff-Qwen3.5-2B to try the 2B model.
set -e
cd "$(dirname "$0")"
LAB="$(pwd)"
MODEL="${JEFF_MODEL:-mstrasser/Jeff-Qwen3.5-0.8B}"
CKPT="checkpoints/$(basename "$MODEL" | tr '[:upper:]' '[:lower:]')"
PORT="${PORT:-8765}"
[ -d jeff ] || git clone --depth 1 https://github.com/firelex/jeff.git
# Jeff pins a minimum uv version. If uv is missing or older, put a private copy in .uv/ (nothing system wide changes).
NEED="$(sed -n 's/^required-version *= *">=\([0-9.]*\)".*/\1/p' jeff/pyproject.toml)"
[ -x "$LAB/.uv/uv" ] && export PATH="$LAB/.uv:$PATH"
HAVE="$(uv --version 2>/dev/null | awk '{print $2}')"
if ! python3 -c "import sys; v=lambda s: tuple(int(x) for x in s.split('.')); sys.exit(0 if '$HAVE' and v('$HAVE') >= v('${NEED:-0}') else 1)" 2>/dev/null; then
  echo "Jeff needs uv ${NEED:-any}, found ${HAVE:-none}. Installing a private copy into $LAB/.uv ..."
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$LAB/.uv" UV_NO_MODIFY_PATH=1 sh
  export PATH="$LAB/.uv:$PATH"
fi
cd jeff
uv sync --extra mac
if [ ! -f "$CKPT/model.safetensors" ]; then
  uv run hf download "$MODEL" --local-dir "$CKPT" --exclude "videos/*" --exclude "assets/*"
fi
if curl -s "localhost:$PORT/health" | grep -q '"ready"'; then
  echo "A Jeff server is already running on port $PORT, using it."
else
  echo "Starting the Jeff server ..."
  JEFF_BACKEND=mlx JEFF_CHECKPOINT="$CKPT" PORT="$PORT" uv run jeff-serve > "$LAB/server.log" 2>&1 &
  SERVER=$!
  trap 'kill $SERVER 2>/dev/null' EXIT
  for i in $(seq 1 150); do
    if curl -s "localhost:$PORT/health" | grep -q '"ready"'; then break; fi
    if ! kill -0 $SERVER 2>/dev/null; then echo "The server stopped. See $LAB/server.log"; exit 1; fi
    sleep 2
  done
fi
curl -s "localhost:$PORT/health"; echo
cd "$LAB"
CPU="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m)"
if [ $# -gt 0 ]; then
  python3 route_check.py --url "http://127.0.0.1:$PORT" --name "$(basename "$MODEL") on $CPU" "$@"
else
  python3 route_check.py --url "http://127.0.0.1:$PORT" --data data/banking77_routes.jsonl --question data/banking77_question.json \
    --name "Banking77 support routing, $(basename "$MODEL") on $CPU" --out results-banking77.json
fi
