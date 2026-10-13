#!/bin/sh
set -e
python -m app.jobs.run migrate
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
