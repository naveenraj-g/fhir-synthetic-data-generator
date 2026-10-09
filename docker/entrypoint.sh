#!/bin/bash
# Starts the three parts of the image: database migration, the API, then the web UI. If either server stops, the whole
# container stops (so Docker can restart it) instead of limping along half-dead.
set -uo pipefail

cd /app/backend
alembic upgrade head || { echo "Database migration failed" >&2; exit 1; }

uvicorn app.main:app --host 0.0.0.0 --port 8000 &
api=$!

cd /app/web
# HOSTNAME must be set: Docker sets it to the container id, which Next would then try to bind to.
HOSTNAME=0.0.0.0 PORT=3000 node server.js &
web=$!

trap 'kill "$api" "$web" 2>/dev/null' TERM INT

wait -n "$api" "$web"
code=$?
echo "A server process exited (code $code); stopping the container." >&2
kill "$api" "$web" 2>/dev/null
wait
exit "$code"
