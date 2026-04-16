# ============================================================
#  VeniceBeach Auto-Booker – Windows Installer
#  Ausfuehren: Rechtsklick auf install.bat → "Als Administrator"
#              ODER in PowerShell:
#              powershell -ExecutionPolicy Bypass -File install.ps1
# ============================================================

param(
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName   = "VeniceBeach-AutoBooker"
$VenvDir    = Join-Path $ScriptDir "venv"
$PythonExe  = Join-Path $VenvDir "Scripts\pythonw.exe"
$PipExe     = Join-Path $VenvDir "Scripts\pip.exe"
$AppPy      = Join-Path $ScriptDir "app.py"
$DbPath     = Join-Path $ScriptDir "fitness.db"
$Launcher   = Join-Path $ScriptDir "start_hidden.vbs"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "  [X]  $msg" -ForegroundColor Red }
function Write-Hr         { Write-Host ("─" * 52) -ForegroundColor Blue }

Write-Hr
Write-Host "  VeniceBeach Auto-Booker  -  Windows Installation" -ForegroundColor White
Write-Hr

# ── 1. Python-Check ──────────────────────────────────────────
Write-Step "Pruefe Python 3..."

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $pythonCmd = $cmd
                Write-Ok "$ver gefunden ($cmd)"
                break
            } else {
                Write-Warn "$ver ist zu alt (benoetigt: 3.10+)"
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Err "Python 3.10+ wurde nicht gefunden."
    Write-Host ""
    Write-Host "  Bitte Python von https://www.python.org/downloads/ herunterladen."
    Write-Host "  Wichtig: Haken bei 'Add Python to PATH' setzen!"
    Write-Host ""
    Read-Host "  Enter druecken zum Beenden"
    exit 1
}

# ── 2. Virtuelle Umgebung ────────────────────────────────────
Write-Step "Erstelle virtuelle Umgebung..."

if (Test-Path $VenvDir) {
    Write-Warn "Virtuelle Umgebung existiert bereits - wird aktualisiert."
} else {
    & $pythonCmd -m venv $VenvDir | Out-Null
    Write-Ok "Virtuelle Umgebung erstellt"
}

# ── 3. Abhaengigkeiten ───────────────────────────────────────
Write-Step "Installiere Abhaengigkeiten..."

& $PipExe install --quiet --upgrade pip 2>&1 | Out-Null
& $PipExe install --quiet -r (Join-Path $ScriptDir "requirements.txt")
Write-Ok "Alle Pakete installiert"

# ── 4. Versteckter Starter (kein Konsolenfenster) ────────────
Write-Step "Erstelle Hintergrund-Starter..."

# VBScript startet pythonw.exe ohne sichtbares Fenster
$vbs = @"
Dim oShell
Set oShell = CreateObject("WScript.Shell")
oShell.Environment("Process")("PORT")    = "$Port"
oShell.Environment("Process")("DB_PATH") = "$DbPath"
oShell.CurrentDirectory = "$ScriptDir"
oShell.Run """$PythonExe"" ""$AppPy""", 0, False
Set oShell = Nothing
"@
Set-Content -Path $Launcher -Value $vbs -Encoding UTF8
Write-Ok "Starter erstellt: start_hidden.vbs"

# ── 5. Aufgabenplaner-Task ───────────────────────────────────
Write-Step "Registriere Autostart-Task..."

# Alten Task entfernen falls vorhanden
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Warn "Alter Task gefunden – wird ersetzt."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action    = New-ScheduledTaskAction `
                 -Execute  "wscript.exe" `
                 -Argument "`"$Launcher`""

$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings  = New-ScheduledTaskSettingsSet `
                 -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
                 -RestartCount 3 `
                 -RestartInterval (New-TimeSpan -Minutes 1) `
                 -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
                 -UserId   $env:USERNAME `
                 -LogonType Interactive `
                 -RunLevel Highest

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $action `
    -Trigger    $trigger `
    -Settings   $settings `
    -Principal  $principal `
    -Description "VeniceBeach Fitness Auto-Booker Webserver" | Out-Null

Write-Ok "Task '$TaskName' im Aufgabenplaner registriert"
Write-Ok "Server startet automatisch bei jedem Windows-Login"

# ── 6. Jetzt starten ─────────────────────────────────────────
Write-Step "Starte Server..."

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

# Pruefen ob pythonw.exe laeuft
$running = Get-Process -Name "pythonw" -ErrorAction SilentlyContinue
if ($running) {
    Write-Ok "Server laeuft im Hintergrund (pythonw.exe, PID $($running[0].Id))"
} else {
    Write-Warn "Server wurde gestartet – pruefe http://localhost:$Port"
}

# ── Fertig ───────────────────────────────────────────────────
Write-Host ""
Write-Hr
Write-Host "  Installation erfolgreich abgeschlossen!" -ForegroundColor Green
Write-Hr
Write-Host ""
Write-Host "  Web-Oberflaeche:  http://localhost:$Port" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Server-Verwaltung:"
Write-Host "    Stoppen:      Aufgabenplanung oeffnen → Task '$TaskName' → Beenden"
Write-Host "    Deinstall:    install.bat /uninstall  ausfuehren"
Write-Host ""

$open = Read-Host "  Browser jetzt oeffnen? (j/n)"
if ($open -ieq "j") {
    Start-Sleep -Seconds 1
    Start-Process "http://localhost:$Port"
}

Write-Host ""
Read-Host "  Enter druecken zum Beenden"
