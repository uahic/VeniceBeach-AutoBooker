#!/usr/bin/env bash
# Start the VeniceBeach auto-booker server (local / non-Docker).
# Usage:  ./start.sh [port]

set -e
cd "$(dirname "$0")"

export PORT="${1:-5000}"
export DB_PATH="${DB_PATH:-$(pwd)/fitness.db}"

# Auto-generate VENICEBEACH_SECRET_KEY on first run and persist it.
KEY_FILE="$(pwd)/.secret_key"
if [ -z "$VENICEBEACH_SECRET_KEY" ]; then
  if [ -f "$KEY_FILE" ]; then
    export VENICEBEACH_SECRET_KEY="$(cat "$KEY_FILE")"
  else
    echo "Generiere neuen Verschlüsselungsschlüssel…"
    export VENICEBEACH_SECRET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    echo "$VENICEBEACH_SECRET_KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "Schlüssel gespeichert in $KEY_FILE (nicht committen!)"
  fi
fi

echo "Starte VeniceBeach Auto-Booker auf Port $PORT…"
echo "  DB:  $DB_PATH"
echo "  Key: ${KEY_FILE}"
python3 app.py
