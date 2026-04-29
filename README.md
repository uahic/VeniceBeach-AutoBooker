# VeniceBeach Karlsruhe Südstadt — AutoBooker

> Geht euch auf der Lauer liegen für eine Kursanmeldung auf den Sack? Mir auch.

Kurse können im Voraus in einem Wochenplan zur automatischen Buchung festgelegt werden. Der Hintergrundprozess (ein Python-Webserver auf Basis von Flask) versucht ab dem ersten möglichen Zeitpunkt jede Minute eine Buchung durchzuführen — oder setzt dich auf die Warteliste, falls der Kurs voll ist.

Die App macht nur als dauerhaft laufender Hintergrundprozess Sinn (Server, NAS, Raspberry Pi, ...). Alles läuft **lokal bei euch** — es wird kein Cloud-Service verwendet.

---

![Login](screenshots/screenshot_login.png)
![Kursliste](screenshots/screenshot_list.png)

---

## Changelog

### v1.2
- Regelmaessige automatische Kursanmeldungen sind nun moeglich

### v1.1
- Wartelisten-Unterstützung: automatisches Beitreten und Verlassen der Warteliste
- Anzeige der Wartelistenposition in der UI
- Bugfixes rund um Wartelisten-Anzeige und -Verwaltung
- Container auf Berliner Zeitzone gesetzt
- UI (bzw. API-Endpoints) sind nun auch lokal Passwortgeschuetzt, unabhaengig davon ob der Server die Credentials bereits kennt oder nicht.

### v1.0
- Erstveröffentlichung

---

## Schnellstart (lokaler Test)

```bash
pip install -r requirements.txt
python app.py
```

Dann im Browser unter `http://localhost:5000` öffnen.

---

## Setup

### Linux

```bash
./install.sh
```

Das Skript erkennt automatisch ob Root-Rechte vorhanden sind. Ohne sudo wird ein **User-Service** unter `~/.config/systemd/user/` angelegt und per `loginctl enable-linger` registriert, sodass der Service auch ohne aktiven Login beim nächsten Neustart startet.

**Was das Skript macht:**

1. Prüft Python 3.10+
2. Erstellt `venv/` und installiert alle Pakete
3. Generiert einen Fernet-Schlüssel und schreibt ihn in `secrets.env` (Berechtigungen: 600)
4. Generiert die systemd-Service-Datei mit korrektem Pfad und User
5. Aktiviert den Service mit `systemctl enable` (autostart beim Booten)
6. Gibt nützliche Verwaltungsbefehle aus

Erreichbar unter `http://localhost:5000`.

**Deinstallation:**

```bash
./install.sh --uninstall
```

---

### Windows

```bat
install.bat
```

**Was das Skript macht:**

1. Ruft `install.ps1` mit umgangener ExecutionPolicy auf (kein manueller Schritt nötig)
2. Prüft Python 3.10+ auf dem System
3. Erstellt `venv/` und installiert alle Pakete
4. Erzeugt `start_hidden.vbs` — startet `pythonw.exe` ohne Konsolenfenster
5. Registriert einen Task im Windows-Aufgabenplaner (autostart bei jedem Login)
6. Fragt ob der Browser direkt geöffnet werden soll

Erreichbar unter `http://localhost:5000`.

**Deinstallation:**

```bat
install.bat /uninstall
```

---

## Sicherheitsaspekte

Nach dem Login werden **E-Mail-Adresse, Passwort und die API-Token** (access_token, refresh_token) lokal gespeichert. Das Passwort wird benötigt, damit die App sich nach einem Token-Ablauf automatisch neu anmelden kann — ohne erneuten manuellen Eingriff.

Alle Zugangsdaten werden **verschlüsselt** abgelegt und liegen zu keinem Zeitpunkt im Klartext auf der Festplatte (Ausnahme: Dev-Modus ohne gesetzten Secret Key).

| Plattform | Speicherort | Verschlüsselung |
|-----------|-------------|-----------------|
| Linux | SQLite-Datenbank | Fernet (symmetrisch), Schlüssel in `$VENICEBEACH_SECRET_KEY` |
| Windows | Windows Credential Manager | OS-seitig via `keyring` |

**Wie `install.sh` den Schlüssel verwaltet (Linux):**

- Generiert beim ersten Installieren einen Fernet-Key und schreibt ihn in `secrets.env` (Berechtigungen: `600`, nur für den eigenen User lesbar)
- Vorhandenes `secrets.env` wird bei Reinstallation **nicht** überschrieben (sonst wären gespeicherte Daten unlesbar)
- Die systemd-Service-Datei lädt `secrets.env` via `EnvironmentFile=`
- Bei Deinstallation wird optional gefragt, ob `secrets.env` gelöscht werden soll
