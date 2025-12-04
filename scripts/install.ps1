# Requires: Windows PowerShell 5.1 or PowerShell 7
# Creates a Python venv and installs project requirements.

param(
    [string]$PythonExe = "python",
    [string]$VenvPath = ".venv"
)

Write-Host "== SensorTest Installer (Windows) =="

# Resolve Python
$pythonCmd = $PythonExe
try {
    & $pythonCmd --version | Out-String | Write-Host
} catch {
    Write-Error "Python not found. Please install Python 3 and re-run."; exit 1
}

# Create venv
Write-Host "Creating virtual environment at '$VenvPath'..."
& $pythonCmd -m venv $VenvPath
if (!(Test-Path "$VenvPath\Scripts\Activate.ps1")) {
    Write-Error "Failed to create venv at '$VenvPath'."; exit 1
}

# Activate venv in this session
$venvActivate = "$VenvPath\Scripts\Activate.ps1"
Write-Host "Activating venv..."
. $venvActivate

# Upgrade pip and install requirements
Write-Host "Upgrading pip..."
python -m pip install --upgrade pip

Write-Host "Installing requirements from requirements.txt..."
pip install -r "$PSScriptRoot\..\requirements.txt"

Write-Host "== Done =="
Write-Host "To activate later: `.$VenvPath\Scripts\Activate.ps1`"
Write-Host "To run: `python find_sensors.py`"

# Notes for Raspberry Pi targets
Write-Host "Note: GPIO libraries require running on a Raspberry Pi."
