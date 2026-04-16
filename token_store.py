"""
Plattform-abhängige Token-Speicherung.

Linux:   access_token + refresh_token werden mit Fernet verschlüsselt in
         der SQLite-DB gespeichert. Der Schlüssel kommt aus der Umgebungs-
         variable VENICEBEACH_SECRET_KEY (wird von install.sh generiert und
         per systemd EnvironmentFile= geladen).

Windows: Tokens werden direkt im Windows Credential Manager gespeichert
         (keyring). Kein eigener Schlüssel nötig – das OS schützt sie.
"""
import os
import platform

_SERVICE = "venicebeach-booker"
_TOKEN_KEYS = ("access_token", "refresh_token")

# ── Windows: Credential Manager ───────────────────────────────────────────────
if platform.system() == "Windows":
    import keyring as _keyring
    import keyring.errors as _kerr

    def get_token(key: str) -> str | None:
        return _keyring.get_password(_SERVICE, key) or None

    def set_token(key: str, value: str):
        if value:
            _keyring.set_password(_SERVICE, key, value)
        else:
            try:
                _keyring.delete_password(_SERVICE, key)
            except _kerr.PasswordDeleteError:
                pass

    def clear_tokens():
        for k in _TOKEN_KEYS:
            try:
                _keyring.delete_password(_SERVICE, k)
            except Exception:
                pass

# ── Linux / macOS: Fernet + SQLite ────────────────────────────────────────────
else:
    import db as _db
    from cryptography.fernet import Fernet as _Fernet, InvalidToken as _InvalidToken

    _fernet = None

    def _cipher():
        """Gibt ein Fernet-Objekt zurück, oder None wenn kein Schlüssel gesetzt."""
        global _fernet
        if _fernet is None:
            raw = os.environ.get("VENICEBEACH_SECRET_KEY", "").strip()
            if raw:
                _fernet = _Fernet(raw.encode())
        return _fernet

    def get_token(key: str) -> str | None:
        value = _db.get_setting(key)
        if not value:
            return None
        f = _cipher()
        if f is None:
            return value          # kein Schlüssel – Klartext (z. B. Dev-Modus)
        try:
            return f.decrypt(value.encode()).decode()
        except (_InvalidToken, Exception):
            return value          # Fallback für Altdaten im Klartext

    def set_token(key: str, value: str):
        if not value:
            _db.set_setting(key, "")
            return
        f = _cipher()
        if f is None:
            _db.set_setting(key, value)
            return
        _db.set_setting(key, f.encrypt(value.encode()).decode())

    def clear_tokens():
        for k in _TOKEN_KEYS:
            _db.set_setting(k, "")
