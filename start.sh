#!/usr/bin/env bash
# Render's start command field rejects chained commands, so the chain lives here
# instead. Tables have to exist before uvicorn accepts a request, so this runs
# first and the shell aborts the start if it fails - better a visible crash loop
# than a live site serving 500s off a half-built schema.
set -euo pipefail

python -m scripts.init_db

# Render supplies PORT; default is only for running this script by hand.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
