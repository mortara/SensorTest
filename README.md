# SensorTest

Textual-based TUI for scanning and displaying sensors on Raspberry Pi GPIO and I2C pins. It detects DHT22, lists I2C device addresses, and shows an interactive table with pin information (mode, level, sensor, info) alongside buttons to start/stop scans. You can also manually assign sensors to pins.

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

Controls (short):
- Start GPIO Scan: scans BCM 2–27 (excluding bus pins) for DHT22.
- Start I2C Scan: scans I2C bus 1 for addresses `0x03`–`0x77`.
- Stop All Scans: cancels running scans.
- Refresh Summary & Table: updates `pinout` summary and the table.
- Select (combobox): manually assigns `DHT22`, `LM393`, or `I2C` to the selected pin.

## Screenshots
Place your screenshots in `docs/` and keep the names below (or adjust the links):

![Main table](docs/screenshot-main.png)
![I2C scan](docs/screenshot-i2c.png)
![DHT22 details](docs/screenshot-dht22.png)

### How to capture (on Raspberry Pi)
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

## Plugin System (GPIO Sensors)
GPIO sensors are loaded dynamically from the `plugins/` folder. Each plugin is a Python file exposing:
- `name: str` — short display name
- `async def detect(pin: int, ctx) -> Optional[(sensor_type, info, color)]` — try to detect sensor on a pin
- `async def read(pin: int, ctx) -> Optional[(sensor_type, info, color)]` — get a reading/state
 - `async def details(phys_pin: int, bcm_pin: int | None, ctx) -> str` — render the details pane content
and a factory function:
```python
def get_plugin():
	return MySensorPlugin()
```
Where `ctx` provides `ctx.GPIO` (RPi.GPIO) and `ctx.gpio_sem` (asyncio.Semaphore) to serialize GPIO access.

Example skeleton (`plugins/template.py`):
```python
import asyncio

class MySensorPlugin:
	name = "MySensor"

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

