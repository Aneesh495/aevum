#!/usr/bin/env bash
set -euo pipefail

checkpoint="${1:?Provide a checkpoint path}"
output="${2:?Provide a new evidence directory}"
port="${PORT:-8078}"
mkdir -p "$(dirname "$output")"
args=(--port "$port" --checkpoint "$checkpoint" --panel "${AEVUM_PANEL:-data/wpp.parquet}" --causes "${AEVUM_CAUSES:-data/who.parquet}")
if [[ -n "${AEVUM_ERRORS:-}" ]]; then args+=(--errors "$AEVUM_ERRORS"); fi
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2 .venv/bin/python -m aevum.dashboard "${args[@]}" > "$output.server.log" 2>&1 &
server="$!"
trap 'kill "$server" 2>/dev/null || true' EXIT
ready=0
for attempt in {1..60}; do
    if curl --fail --silent --max-time 1 "http://127.0.0.1:$port/api/catalogue" >/dev/null; then
        ready=1
        break
    fi
    kill -0 "$server" 2>/dev/null || break
    sleep .2
done
if [[ "$ready" != 1 ]]; then
    cat "$output.server.log"
    exit 1
fi
AEVUM_QA_URL="http://127.0.0.1:$port" node web/tests/dashboard.cjs "$output"
