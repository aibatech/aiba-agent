$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
Write-Host "`nAIBA Agent Installer" -ForegroundColor Cyan
Write-Host "Checking your computer..."
$Python = $null
try { & py -3.11 -c "import sys; assert sys.version_info >= (3,11)"; if ($LASTEXITCODE -eq 0) { $Python = "py"; $PythonArgs = @("-3.11") } } catch {}
if (-not $Python) { try { & python -c "import sys; assert sys.version_info >= (3,11)"; if ($LASTEXITCODE -eq 0) { $Python = "python"; $PythonArgs = @() } } catch {} }
if (-not $Python) {
  Write-Host "Python 3.11 or newer is required." -ForegroundColor Red
  Write-Host "Install it from https://www.python.org/downloads/windows/ and check 'Add Python to PATH', then run this installer again."
  exit 1
}
Write-Host "Creating AIBA's private environment..."
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $Python @PythonArgs -m venv .venv }
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install ".[api]"
& ".venv\Scripts\python.exe" setup_cli.py --no-browser
Write-Host "Running a final system check..."
& ".venv\Scripts\python.exe" main.py --doctor
if ($env:AIBA_INSTALL_NO_LAUNCH -eq "true") { Write-Host "Headless installation certification passed." -ForegroundColor Green; exit 0 }
$envLine = Get-Content .env | Where-Object { $_ -match '^AIBA_API_TOKEN=' } | Select-Object -First 1
$token = ($envLine -split '=',2)[1].Trim('"')
Write-Host "Starting AIBA Agent..." -ForegroundColor Green
Start-Process -FilePath ".venv\Scripts\pythonw.exe" -ArgumentList "aiba_launcher.py --serve" -WorkingDirectory $Root
$ready = $false
for ($attempt=0; $attempt -lt 30; $attempt++) {
  try { Invoke-RestMethod -Uri "http://127.0.0.1:8765/ready" -TimeoutSec 2 | Out-Null; $ready=$true; break } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw "AIBA did not become ready. Run .venv\Scripts\python.exe main.py --doctor for a diagnosis." }
Start-Process ("http://127.0.0.1:8765/#token=" + [uri]::EscapeDataString($token))
Write-Host "AIBA Agent is installed and running. Use Start-AIBA-Windows.bat next time." -ForegroundColor Green
