# SensorTest

Textual-based TUI for scanning and displaying sensors on Raspberry Pi GPIO and I2C pins. It auto-detects supported GPIO sensors (e.g. DHT22, DS18B20, BMP280, PIR HC-SR501, Button, LM393) and lists I2C device addresses. The UI shows an interactive table with pin information (mode, level, sensor, info) plus concise controls for starting/stopping scans and assigning sensors manually.

## Requirements
- Raspberry Pi OS (Bullseye/Bookworm) with Python 3
- I2C enabled in the system (`raspi-config`)
- Optional: system tools `pinout`/`pintest` for a pin summary

## Installation
APT (recommended on Raspberry Pi):
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-rpi.gpio python3-smbus i2c-tools python3-gpiozero
```
Python packages (TUI and sensors):
```bash
python3 -m pip install --upgrade pip
python3 -m pip install textual Adafruit_DHT gpiozero
```
## Quick Setup
- Windows (PowerShell):
```powershell
cd d:\PMortara\Dokumente\VSCodeProjects\SensorTest\scripts
./install.ps1
```

- Raspberry Pi (Bash):
```bash
cd SensorTest/scripts
chmod +x install.sh
./install.sh
```

After installation, activate the virtual environment and run:
```powershell
.\.venv\Scripts\Activate.ps1; python find_sensors.py
```
or on Raspberry Pi:
```bash
source .venv/bin/activate
python find_sensors.py
```

All dependencies are listed in `requirements.txt`. GPIO-related packages only work on Raspberry Pi.

Notes:
- `RPi.GPIO` typically comes via APT (`python3-rpi.gpio`).
- The `smbus` module is provided by `python3-smbus` (needed for I2C scan).

## Usage
Start the app:
```bash
python3 find_sensors.py
```
If you see permission errors (GPIO/I2C):
```bash
sudo -E python3 find_sensors.py
```

Controls:
- Scan GPIO: safe auto-detect scan over BCM 2–27 (excluding bus pins) for all auto-detectable plugins.
- Scan I2C: scans I2C bus 1 for addresses `0x03`–`0x77` and marks found devices.
- Scan Pin: performs a safe single-pin scan (excludes bus pins) using auto-detectable plugins.
- Stop All: cancels any running GPIO or I2C scans.
- Assign sensor (select): manually tag a pin with a sensor name (`I2C`, or any loaded plugin) so periodic reads keep it updated.

## Screenshots
Place your screenshots in `docs/` and keep the names below (or adjust the links):

![Main table](docs/screenshot-main.png)
![I2C scan](docs/screenshot-i2c.png)
![DHT22 details](docs/screenshot-dht22.png)

### How to Capture (on Raspberry Pi)
- With GUI: install `scrot` and take a snapshot
	```bash
	sudo apt update
	sudo apt install -y scrot
	scrot ~/screenshot.png
	```
- From another machine: open the TUI in a larger terminal window and use your OS screenshot tool, then copy the images into `docs/`.

## Tips & Troubleshooting
- `ModuleNotFoundError: smbus`: `sudo apt install python3-smbus`
- Missing `pinout`: `sudo apt install python3-gpiozero`
- I2C disabled: `sudo raspi-config` → Interface Options → enable I2C, then reboot
- No GPIO permissions: `sudo usermod -aG gpio $USER` and reboot

License: see `LICENSE`.

## Code Layout

```
find_sensors.py        # Minimal entrypoint calling sensorapp.gpio_app.run_app()
sensorapp/
	gpio_app.py          # Main Textual application (GPIOApp) + run_app()
	pin_table.py         # PinTable widget abstraction (columns + update helper)
	plugins_loader.py    # Dynamic discovery + fallback loader + options builder
plugins/               # Individual sensor plugins (get_plugin factory per file)
```

### Module Responsibilities
- `find_sensors.py`: Keeps startup logic tiny; no business code.
- `sensorapp/gpio_app.py`: Event handlers, scanning workflows (GPIO/I2C), periodic polling, detail rendering.
- `sensorapp/pin_table.py`: Encapsulates table schema and update logic.
- `sensorapp/plugins_loader.py`: Robust plugin import with fallback compilation (future annotations) and option list construction.
- `plugins/*.py`: Each implements `get_plugin()` returning an instance with `name`, `auto_detectable`, and async `detect/read/details` methods.

### Extending
- New sensor: add `plugins/<sensor>.py` with `get_plugin()`; no changes to core needed.
- Additional UI panes: create new widget/module under `sensorapp/` and import in `gpio_app.py`.
- Tests: add `tests/` (e.g. async detection mocks) isolating plugin logic.
- Configuration: use environment variables (e.g. `SENSOR_PLUGINS_DIR`) or introduce a `config.py` in `sensorapp/` for structured settings.

### Design Notes
- Hardware access serialized via a single `asyncio.Semaphore` (`gpio_sem`) to avoid race conditions on GPIO.
- Scans use timeouts (`SCAN_PLUGIN_TIMEOUT`) preventing hangs on misbehaving plugins.
- Periodic polling task is cancelled during active GPIO scan to avoid contention.
- I2C detection intentionally minimal (`write_quick`) to stay generic across devices.

## Plugin System (GPIO Sensors)
GPIO sensors are loaded dynamically from the `plugins/` folder. Each plugin is a Python file exposing:
- `name: str` — short display name
- `bus_type: str` — optional; classify device bus (e.g., `GPIO`, `I2C`, `SPI`)
- `pin_roles: list[str]` — optional; define role names for multi-pin devices (e.g., `["CLK","DIO"]`)
- `async def detect(pin: int, ctx) -> Optional[(sensor_type, info, color)]` — try to detect sensor on a pin
- `async def read(pin: int, ctx) -> Optional[(sensor_type, info, color)]` — get a reading/state
- `async def details(phys_pin: int, bcm_pin: int | None, ctx) -> str` — render the details pane content
and a factory function:
```python
def get_plugin():
	return MySensorPlugin()
```
Where `ctx` provides `ctx.GPIO` (RPi.GPIO), `ctx.gpio_sem` (asyncio.Semaphore) to serialize GPIO access, and `ctx.role_pin_assignments` mapping `(sensor_name, role) -> bcm_pin` for multi-pin plugins.

Example skeleton (`plugins/template.py`):
```python
import asyncio

class MySensorPlugin:
	name = "MySensor"
	bus_type = "GPIO"
	pin_roles = ["DATA"]

	async def detect(self, pin: int, ctx):
		# Optional quick detection logic; return None if not detected
		try:
			async with ctx.gpio_sem:
				ctx.GPIO.setup(pin, ctx.GPIO.IN)
				value = ctx.GPIO.input(pin)
			return (self.name, f"value={value}", "blue")
		except Exception:
			return None

	async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
		header = f"Pin {phys_pin}"
		# Use assigned DATA role if present
		assigned = getattr(ctx, "role_pin_assignments", {}).get((self.name, "DATA"))
		if assigned is not None:
			bcm_pin = assigned
		try:
			if bcm_pin is not None:
				res = await self.read(bcm_pin, ctx)
				if res:
					_, info, _ = res
					return f"{header}\nSensor: {self.name}\n{info}"
		except Exception:
			pass
	return f"{header}\nSensor: {self.name}\nReading unavailable"

	async def read(self, pin: int, ctx):
		# Return a concise reading or state
		try:
			async with ctx.gpio_sem:
				ctx.GPIO.setup(pin, ctx.GPIO.IN)
				value = ctx.GPIO.input(pin)
			return (self.name, f"value={value}", "blue")
		except Exception:
			return None

def get_plugin():
	return MySensorPlugin()
```

### Assigning Multi-Pin Roles
- The sensor select box lists role-specific options when a plugin provides `pin_roles` (e.g., `TM1637:CLK`, `TM1637:DIO`).
- Assign each role to the appropriate BCM pin; plugins can then read these assignments from `ctx.role_pin_assignments`.
- For I2C devices (e.g., BMP280), `bus_type = "I2C"` and `pin_roles = ["SDA","SCL"]` are provided for consistency; detection uses the I2C bus, not per-pin scanning.

### Plugin Roles
| Plugin | `bus_type` | `pin_roles` | Auto-detect |
| - | - | - | - |
| DHT22 | GPIO | [DATA] | yes |
| LM393 | GPIO | [DATA] | no |
| DS18B20 | GPIO | [DATA] | yes |
| PIR HC-SR501 | GPIO | [DATA] | no |
| Button | GPIO | [DATA] | no |
| BMP280 | I2C | [SDA, SCL] | yes |
| TM1637 | GPIO | [CLK, DIO] | no |

