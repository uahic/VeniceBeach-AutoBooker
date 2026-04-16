#!/usr/bin/env bash
# ============================================================
#  VeniceBeach Auto-Booker – Linux Installer / Deinstaller
#
#  Installation:    bash install.sh
#  Deinstallation:  bash install.sh --uninstall
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

step() { echo -e "\n${BLUE}==>${NC} ${BOLD}$1${NC}"; }
ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
err()  { echo -e "  ${RED}✗${NC}  $1"; }
hr()   { echo -e "${BLUE}────────────────────────────────────────────────${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="venicebeach-booker"
VENV="$SCRIPT_DIR/venv"
PORT="${PORT:-5000}"

# Wird sudolos als User-Service installiert, oder systemweit?
# Entscheidung: sudo verfügbar UND Nutzer ist kein root-loser User → System
HAS_SUDO=false
if [[ "$EUID" -eq 0 ]]; then
    HAS_SUDO=true
elif sudo -n true 2>/dev/null; then
    HAS_SUDO=true
fi

# ── Hilfsfunktionen systemctl ─────────────────────────────────
ctl_system() { sudo systemctl "$@"; }
ctl_user()   { systemctl --user "$@"; }

service_ctl() {
    if $HAS_SUDO; then ctl_system "$@"; else ctl_user "$@"; fi
}

# ════════════════════════════════════════════════════════════
#  DEINSTALLATION
# ════════════════════════════════════════════════════════════
if [[ "${1:-}" == "--uninstall" ]]; then
    hr
    echo -e "  ${BOLD}VeniceBeach Auto-Booker  –  Deinstallation${NC}"
    hr

    REMOVED=false

    # System-Service entfernen (falls vorhanden)
    SYSTEM_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    if [[ -f "$SYSTEM_FILE" ]]; then
        step "Entferne System-Service..."
        sudo systemctl stop    "$SERVICE_NAME" 2>/dev/null || true
        sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
        sudo rm -f "$SYSTEM_FILE"
        sudo systemctl daemon-reload
        ok "System-Service entfernt"
        REMOVED=true
    fi

    # User-Service entfernen (falls vorhanden)
    USER_SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    USER_FILE="$USER_SERVICE_DIR/${SERVICE_NAME}.service"
    if [[ -f "$USER_FILE" ]]; then
        step "Entferne User-Service..."
        systemctl --user stop    "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
        rm -f "$USER_FILE"
        systemctl --user daemon-reload
        ok "User-Service entfernt"
        REMOVED=true
    fi

    if ! $REMOVED; then
        warn "Kein installierter Service gefunden."
    fi

    # Verschlüsselungsschlüssel entfernen?
    SECRETS_FILE="$SCRIPT_DIR/secrets.env"
    if [[ -f "$SECRETS_FILE" ]]; then
        echo ""
        read -rp "  Verschlüsselungsschlüssel (secrets.env) löschen? Tokens in der DB werden dann unlesbar. [j/N] " yn
        if [[ "${yn,,}" == "j" ]]; then
            rm -f "$SECRETS_FILE"
            ok "secrets.env gelöscht"
        fi
    fi

    # Virtuelle Umgebung entfernen?
    if [[ -d "$VENV" ]]; then
        echo ""
        read -rp "  Virtuelle Umgebung ($VENV) ebenfalls löschen? [j/N] " yn
        if [[ "${yn,,}" == "j" ]]; then
            rm -rf "$VENV"
            ok "Virtuelle Umgebung gelöscht"
        fi
    fi

    echo ""
    hr
    echo -e "  ${GREEN}${BOLD}Deinstallation abgeschlossen.${NC}"
    hr
    echo ""
    exit 0
fi

# ════════════════════════════════════════════════════════════
#  INSTALLATION
# ════════════════════════════════════════════════════════════
hr
echo -e "  ${BOLD}VeniceBeach Auto-Booker  –  Installation${NC}"
hr

if $HAS_SUDO; then
    echo -e "  Modus: ${GREEN}System-Service${NC} (startet automatisch beim Booten)"
else
    echo -e "  Modus: ${YELLOW}User-Service${NC} (kein sudo gefunden – läuft nur wenn du eingeloggt bist)"
fi

# ── 1. Python-Check ──────────────────────────────────────────
step "Prüfe Python 3..."

if ! command -v python3 &>/dev/null; then
    err "Python 3 wurde nicht gefunden."
    echo ""
    echo "  Bitte installiere Python 3.10 oder neuer:"
    echo "    Ubuntu / Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "    Fedora / RHEL:    sudo dnf install python3"
    echo "    Arch:             sudo pacman -S python"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 10 ) ]]; then
    err "Python 3.10 oder neuer wird benötigt (gefunden: $PY_VER)."
    exit 1
fi
ok "Python $PY_VER"

# ── 2. Virtuelle Umgebung ────────────────────────────────────
step "Erstelle virtuelle Umgebung..."

if [[ -d "$VENV" ]]; then
    warn "Virtuelle Umgebung existiert bereits – wird aktualisiert."
else
    python3 -m venv "$VENV"
    ok "Virtuelle Umgebung erstellt: $VENV"
fi

# ── 3. Abhängigkeiten ────────────────────────────────────────
step "Installiere Abhängigkeiten..."

"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
ok "Alle Pakete installiert"

# ── 4. Verschlüsselungsschlüssel ─────────────────────────────
SECRETS_FILE="$SCRIPT_DIR/secrets.env"
step "Richte Verschlüsselungsschlüssel ein..."

if [[ -f "$SECRETS_FILE" ]]; then
    warn "secrets.env existiert bereits – Schlüssel wird beibehalten."
else
    FERNET_KEY=$("$VENV/bin/python" -c \
        "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    printf 'VENICEBEACH_SECRET_KEY=%s\n' "$FERNET_KEY" > "$SECRETS_FILE"
    chmod 600 "$SECRETS_FILE"
    ok "Schlüssel generiert und in secrets.env gespeichert (nur für dich lesbar)"
fi

# ── 5. systemd-Service ───────────────────────────────────────
if ! command -v systemctl &>/dev/null; then
    warn "systemd nicht gefunden – Service wird übersprungen."
    echo ""
    echo "  Manuell starten mit:"
    echo -e "    ${BLUE}cd $SCRIPT_DIR && ./start.sh${NC}"
    exit 0
fi

step "Installiere systemd-Service..."

TMP_SERVICE=$(mktemp)

if $HAS_SUDO; then
    # ── System-weiter Service ──────────────────────────────
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    cat > "$TMP_SERVICE" <<EOF
[Unit]
Description=VeniceBeach Fitness Auto-Booker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${VENV}/bin/python app.py
Restart=always
RestartSec=10
EnvironmentFile=${SECRETS_FILE}
Environment=PORT=${PORT}
Environment=DB_PATH=${SCRIPT_DIR}/fitness.db

[Install]
WantedBy=multi-user.target
EOF
    if [[ "$EUID" -ne 0 ]]; then
        sudo cp "$TMP_SERVICE" "$SERVICE_FILE"
    else
        cp "$TMP_SERVICE" "$SERVICE_FILE"
    fi
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
    ok "System-Service installiert und gestartet"

else
    # ── User-Service (kein sudo nötig) ─────────────────────
    USER_SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$USER_SERVICE_DIR"
    USER_FILE="$USER_SERVICE_DIR/${SERVICE_NAME}.service"

    cat > "$TMP_SERVICE" <<EOF
[Unit]
Description=VeniceBeach Fitness Auto-Booker
After=network.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${VENV}/bin/python app.py
Restart=always
RestartSec=10
EnvironmentFile=${SECRETS_FILE}
Environment=PORT=${PORT}
Environment=DB_PATH=${SCRIPT_DIR}/fitness.db

[Install]
WantedBy=default.target
EOF
    cp "$TMP_SERVICE" "$USER_FILE"
    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    systemctl --user restart "$SERVICE_NAME"
    ok "User-Service installiert und gestartet"

    # Linger aktivieren: Service läuft auch ohne aktive Login-Session
    # (z. B. nach Neustart auf Servern/Headless-Systemen)
    if command -v loginctl &>/dev/null; then
        if loginctl enable-linger "$(whoami)" 2>/dev/null; then
            ok "Linger aktiviert – Service startet auch ohne Login"
        else
            warn "Linger konnte nicht aktiviert werden (kein sudo)."
            warn "Der Service läuft nur, solange du eingeloggt bist."
            warn "Für automatischen Start beim Booten: sudo loginctl enable-linger $(whoami)"
        fi
    fi
fi

rm "$TMP_SERVICE"

# ── 5. Status prüfen ─────────────────────────────────────────
sleep 2
if service_ctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    ok "Service läuft!"
else
    err "Service konnte nicht gestartet werden. Fehlerausgabe:"
    service_ctl status "$SERVICE_NAME" --no-pager -l || true
    exit 1
fi

# ── Fertig ───────────────────────────────────────────────────
echo ""
hr
echo -e "  ${GREEN}${BOLD}Installation erfolgreich abgeschlossen!${NC}"
hr
echo ""
echo -e "  Web-Oberfläche:  ${BLUE}http://localhost:${PORT}${NC}"
echo ""
echo "  Nützliche Befehle:"

if $HAS_SUDO; then
    CTL="sudo systemctl"
    LOG="sudo journalctl -u $SERVICE_NAME -f"
else
    CTL="systemctl --user"
    LOG="journalctl --user -u $SERVICE_NAME -f"
fi

printf "    %-52s  Status anzeigen\n"  "$CTL status  $SERVICE_NAME"
printf "    %-52s  Stoppen\n"          "$CTL stop    $SERVICE_NAME"
printf "    %-52s  Starten\n"          "$CTL start   $SERVICE_NAME"
printf "    %-52s  Logs live\n"        "$LOG"
echo ""
echo "  Deinstallation:"
echo "    bash install.sh --uninstall"
echo ""
