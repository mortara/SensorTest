#!/usr/bin/env bash
set -euo pipefail

PYTHON=${PYTHON:-python3}
VENV_PATH=${VENV_PATH:-.venv}

echo "== SensorTest Installer (Linux/Raspberry Pi) =="

# Basic prerequisites
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv python3-dev libi2c-dev i2c-tools wiringpi

# Optional: enable I2C and 1-Wire (requires reboot)
if command -v raspi-config >/dev/null 2>&1; then
  echo "Enabling I2C via raspi-config (non-interactive)"
  sudo raspi-config nonint do_i2c 0
  echo "Enabling 1-Wire via raspi-config (non-interactive)"
  sudo raspi-config nonint do_onewire 0
fi

# Create venv
echo "Creating virtual environment at '$VENV_PATH'..."
$PYTHON -m venv "$VENV_PATH"
source "$VENV_PATH/bin/activate"

# Upgrade pip and install requirements
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "== Done =="
echo "To activate later: 'source $VENV_PATH/bin/activate'"
echo "To run: 'python find_sensors.py'"
