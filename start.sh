#!/usr/bin/env bash
# Start the VeniceBeach auto-booker server.
# Usage:  ./start.sh [port]
# Default port: 5000

cd "$(dirname "$0")"
export PORT="${1:-5000}"
export DB_PATH="${DB_PATH:-fitness.db}"

python3 app.py
