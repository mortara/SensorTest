from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from pathlib import Path
import RPi.GPIO as GPIO
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Select
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable

from .pin_table import PinTable
from .plugins_loader import load_gpio_plugins, build_plugin_options

# Tuning constants
SCAN_PLUGIN_TIMEOUT = 0.5
SCAN_PIN_DELAY = 0.1
I2C_SCAN_DELAY = 0.05

# SMBus for I2C
try:
    import smbus
    HAS_SMBUS = True
except Exception:
    HAS_SMBUS = False

GPIO.setmode(GPIO.BCM)
PIN_MAP = {2:"I2C SDA",3:"I2C SCL",14:"UART TX",15:"UART RX",10:"SPI MOSI",9:"SPI MISO",11:"SPI SCLK",8:"SPI CE0",7:"SPI CE1"}
BUS_PINS = set(PIN_MAP.keys())

class GPIOApp(App):
    CSS = """
    Screen {layout: vertical;}
    #buttons {border: round yellow; padding: 1; height: auto;}
    #buttons Button {border: round yellow; padding: 0 1; margin: 0 1;}
    #topinfo {height: 10; min-height:3;}
    #summary {border: round cyan; padding: 1; width: 1fr; height: 1fr; overflow: auto;}
    #right {height: 1fr;}
    #status {padding: 1; height: 3;}
    #details {border: round yellow; padding: 1; width: 1fr; height: 1fr; min-height:3; overflow: auto;}
    #table {border: round green; padding: 1; height: 1fr;}
    #select {border: round yellow; padding: 1; height: auto;}
    """
    status_text: reactive[str] = reactive("")

    def __init__(self):
        super().__init__()
        self.gpio_task = None
        self.i2c_task = None
        self.fixed_pin_sensors = {}
        self.last_row_key = None
        self.sensor_poll_task = None
        self.gpio_sem = asyncio.Semaphore(1)
        self.auto_detect_enabled = True
        self.numbering_mode = "BCM"
        self.PHYS_TO_BCM = {
            3: 2, 5: 3, 7: 4, 8: 14, 10: 15, 11: 17, 12: 18, 13: 27, 15: 22,
            16: 23, 18: 24, 19: 10, 21: 9, 22: 25, 23: 11, 24: 8, 26: 7,
            29: 5, 31: 6, 32: 12, 33: 13, 35: 19, 36: 16, 37: 26, 38: 20, 40: 21
        }
        self.NON_GPIO_HW = {1:"3V3",2:"5V",4:"5V",6:"GND",9:"GND",17:"3V3",20:"GND",25:"GND",30:"GND",34:"GND",39:"GND"}
        self.BCM_TO_PHYS = {bcm: phys for phys, bcm in self.PHYS_TO_BCM.items()}
        print("[startup] Loading plugins...")
        self.gpio_plugins = load_gpio_plugins()
        print(f"[startup] Plugins loaded: {', '.join(sorted(self.gpio_plugins.keys())) if self.gpio_plugins else 'none'}")
        class _PluginCtx:
            def __init__(self, gpio, sem):
                self.GPIO = gpio
                self.gpio_sem = sem
        self.plugin_ctx = _PluginCtx(GPIO, self.gpio_sem)

    # Helpers
    def _set_scan_marker(self, bcm_pin:int, text:str, color:str="yellow"):
        try:
            disp = self.get_display_pin(bcm_pin)
            self.table.update_sensor(disp, text, "", color=color)
        except Exception:
            pass

    def _set_sensor_result(self, bcm_pin:int, sensor_type:str, info:str, color:str):
        try:
            disp = self.get_display_pin(bcm_pin)
            self.table.update_sensor(disp, sensor_type, info, color=color)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        self.btn_gpio = Button("Scan GPIO", id="btn_gpio")
        self.btn_i2c = Button("Scan I2C", id="btn_i2c")
        self.btn_stop_all = Button("Stop All", id="btn_stop_all")
        self.btn_scan_selected = Button("Scan Pin", id="btn_scan_selected")
        self.btn_refresh_summary = Button("Refresh Summary", id="btn_refresh_summary")
        plugin_options = build_plugin_options(self.gpio_plugins)
        self.sensor_select = Select(options=plugin_options, allow_blank=True, prompt="Assign sensor", id="sensor_select")
        yield Horizontal(self.btn_gpio, self.btn_i2c, self.btn_stop_all, self.sensor_select, self.btn_scan_selected, self.btn_refresh_summary, id="buttons")
        self.table = PinTable(); self.table.id = "table"
        try:
            self.table.cursor_type = "row"; self.table.show_cursor = True
        except Exception:
            pass
        self.summary_widget = Static("", id="summary")
        self.status_widget = Static("", id="status")
        self.detail_widget = Static("", id="details")
        right_side = Vertical(self.status_widget, self.detail_widget, id="right")
        # Show a placeholder so the UI isn't blank before async summary loads
        try:
            self.summary_widget.update("[yellow]Loading pin summary...[/yellow]")
        except Exception:
            pass
        yield Horizontal(self.summary_widget, right_side, id="topinfo")
        self.build_table_rows()
        yield self.table
        yield Footer()

    def watch_status_text(self,value:str):
        try:
            if hasattr(self, "status_widget") and self.status_widget is not None:
                self.status_widget.update(f"[yellow]{value}[/yellow]")
        except Exception:
            pass

    async def on_mount(self):
        try:
            if hasattr(self, "sensor_select"):
                self.sensor_select.set_options(build_plugin_options(self.gpio_plugins))
        except Exception:
            pass
        # Populate pin summary at startup in background to avoid blocking the UI
        # Defer summary load until user requests (avoid startup hangs)
        try:
            self.summary_widget.update("[yellow]Summary idle. Press 'Refresh Summary'.[/yellow]")
        except Exception:
            pass
        if self.sensor_poll_task is None or self.sensor_poll_task.done():
            self.sensor_poll_task = asyncio.create_task(self.poll_sensors_periodically())

    async def on_unmount(self):
        if self.sensor_poll_task and not self.sensor_poll_task.done():
            self.sensor_poll_task.cancel()

    def build_table_rows(self):
        try:
            self.table.clear(); self.table.pin_to_row.clear()
        except Exception:
            pass
        pins = self.get_system_pin_info()
        if not pins:
            self.status_text = "No pin info from system tools; showing placeholders"
            for phys in range(1,41):
                row_key = self.table.add_row(str(phys), "", "", "N/A", "N/A", "[red]-[/red]", "")
                self.table.pin_to_row[phys] = row_key
            return
        self.BCM_TO_PHYS = {}
        for entry in pins:
            bcm_v = entry.get("bcm")
            if bcm_v is not None:
                self.BCM_TO_PHYS[bcm_v] = entry["phys"]
        for entry in pins:
            phys = entry.get("phys"); bcm = entry.get("bcm"); board_func = entry.get("name", "")
            if bcm is not None and (board_func == "GPIO" or board_func == ""):
                bcm_map = {2:"I2C SDA",3:"I2C SCL",14:"UART TX",15:"UART RX",10:"SPI MOSI",9:"SPI MISO",11:"SPI SCLK",8:"SPI CE0",7:"SPI CE1"}
                board_func = bcm_map.get(bcm, board_func)
            bcm_str = str(bcm) if bcm is not None else ""
            try:
                if bcm is not None:
                    mode = GPIO.gpio_function(bcm)
                    mode_str = "INPUT" if mode==GPIO.IN else "OUTPUT" if mode==GPIO.OUT else f"ALT{mode}"
                    lvl = GPIO.input(bcm)
                    lvl_str = "HIGH" if lvl else "LOW"
                else:
                    mode_str = "N/A"; lvl_str = "N/A"
            except Exception:
                mode_str = "N/A"; lvl_str = "N/A"
            info_extra = []
            try:
                import gpiozero
                pwm_capable_bcms = {12, 13, 18, 19}
                if bcm is not None:
                    info_extra.append(f"PWM:{'Y' if bcm in pwm_capable_bcms else 'N'}")
            except Exception:
                pass
            info_str = " ".join(info_extra) if info_extra else ""
            row_key = self.table.add_row(str(phys), bcm_str, board_func, mode_str, lvl_str, "[red]-[/red]", info_str)
            self.table.pin_to_row[phys] = row_key
        try:
            self.refresh_gpio_states()
        except Exception:
            pass

    def refresh_gpio_states(self):
        if not hasattr(self, "gpio_sem"):
            import asyncio as _asyncio; self.gpio_sem = _asyncio.Semaphore(1)
        if not hasattr(self, "scanning"): self.scanning = False
        try:
            if GPIO.getmode() is None: GPIO.setmode(GPIO.BCM)
        except Exception: return
        try:
            self.scanning = True
            import asyncio as _asyncio
            async def _do_refresh():
                async with self.gpio_sem:
                    for phys, row_key in list(self.table.pin_to_row.items()):
                        try:
                            bcm_cell = self.table.get_cell(row_key, 1)
                            bcm = int(bcm_cell) if str(bcm_cell).isdigit() else None
                            if bcm is None: continue
                            mode = GPIO.gpio_function(bcm)
                            mode_str = "INPUT" if mode==GPIO.IN else "OUTPUT" if mode==GPIO.OUT else f"ALT{mode}"
                            lvl = GPIO.input(bcm); lvl_str = "HIGH" if lvl else "LOW"
                            self.table.update_cell(row_key, 3, mode_str); self.table.update_cell(row_key, 4, lvl_str)
                        except Exception: continue
            loop = None
            try: loop = _asyncio.get_event_loop()
            except RuntimeError: loop = None
            if loop and loop.is_running(): loop.create_task(_do_refresh())
            else: _asyncio.run(_do_refresh())
        finally:
            self.scanning = False

    def get_system_pin_info(self):
        def try_cmd(cmd:list[str]):
            try: return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
            except Exception: return None
        out = try_cmd(["pinout"]) or ""; pins = []
        if not out: return pins
        lines = out.splitlines(); import re as _re
        j8_index = None
        for idx, ln in enumerate(lines):
            if ln.strip().startswith("J8:"): j8_index = idx; break
        if j8_index is not None:
            for ln in lines[j8_index+1:]:
                if not ln.strip(): break
                m = _re.match(r"^\s*(\S+)\s*\((\d+)\)\s*\((\d+)\)\s*(\S+)\s*$", ln)
                if not m: m = _re.match(r"^\s*(\S+)\s*\((\d+)\)\s*\((\d+)\)\s*(.+?)\s*$", ln)
                if m:
                    left_name = m.group(1).strip(); left_phys = int(m.group(2)); right_phys = int(m.group(3)); right_name = m.group(4).strip()
                    def to_entry(name_str, phys):
                        name_up = name_str.upper(); bcm = None; board_name = name_str
                        if name_up.startswith("GPIO") and name_up[4:].isdigit(): bcm = int(name_up[4:]); board_name = "GPIO"
                        elif name_up in ("3V3", "3.3V"): board_name = "3V3"
                        elif name_up in ("5V"): board_name = "5V"
                        elif name_up in ("GND", "GROUND"): board_name = "GND"
                        return {"phys": phys, "bcm": bcm, "name": board_name}
                    pins.append(to_entry(left_name, left_phys)); pins.append(to_entry(right_name, right_phys))
        if not pins:
            for ln in lines:
                m = _re.search(r"GPIO\s*(\d+)\s*(?:\(([^)]+)\))?.*?physical\s*pin\s*(\d+)", ln, _re.IGNORECASE)
                if m:
                    bcm = int(m.group(1)); label = (m.group(2) or "").strip(); phys = int(m.group(3)); label_upper = label.upper()
                    name_map = {"SDA":"I2C SDA","SDA1":"I2C SDA","SCL":"I2C SCL","SCL1":"I2C SCL","TXD":"UART TX","RXD":"UART RX","MOSI":"SPI MOSI","MISO":"SPI MISO","SCLK":"SPI SCLK","SCK":"SPI SCLK","CE0":"SPI CE0","CE1":"SPI CE1"}
                    name = name_map.get(label_upper, label) if label else "GPIO"
                    pins.append({"phys": phys, "bcm": bcm, "name": name})
            for ln in lines:
                m = _re.search(r"(3V3|3\.3V|5V|GND|GROUND).+physical\s*pin\s*(\d+)", ln, _re.IGNORECASE)
                if m:
                    phys = int(m.group(2)); name_raw = m.group(1).upper(); name = "3V3" if name_raw in ("3.3V", "3V3") else ("GND" if name_raw in ("GND", "GROUND") else name_raw)
                    if all(p.get("phys") != phys for p in pins): pins.append({"phys": phys, "bcm": None, "name": name})
        pins.sort(key=lambda x: x.get("phys", 0)); return pins

    async def update_pin_summary(self):
        # Try pintest -> pinout (-r) -> pinout -> gpio readall; show truncated output
        def try_cmd(cmd:list[str]):
            try:
                print(f"[pin-summary] Running: {' '.join(cmd)} (timeout 3s)")
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if out.returncode != 0:
                    raise RuntimeError(out.stderr.strip() or f"exit {out.returncode}")
                text = (out.stdout or "").strip()
                print(f"[pin-summary] Success: {' '.join(cmd)}; first lines:\n" + "\n".join(out.splitlines()[:6]))
                return text
            except Exception as e:
                print(f"[pin-summary] Failed: {' '.join(cmd)} -> {e}")
                return None

        print("[pin-summary] Start collecting pin summary...")
        output = await asyncio.to_thread(try_cmd, ["pinout"])
        title = "pinout"

        if output:
            lines = [ln for ln in output.splitlines() if ln.strip()]
            summary = "\n".join(lines[:18]) if lines else "No output"
            try:
                self.summary_widget.update(f"[cyan]{title} summary:[/cyan]\n{summary}")
                self.status_text = f"Using {title} for pin info"
                print(f"[pin-summary] Displaying {title} summary (truncated to 18 lines).")
            except Exception:
                pass
        else:
            try:
                self.summary_widget.update("[red]No pin summary available[/red]\nInstall 'python3-gpiozero' for 'pinout' or 'wiringpi' for 'gpio readall'.")
                self.status_text = "No pin info source available"
                print("[pin-summary] No pin summary source available. Suggest installing gpiozero/wiringpi.")
            except Exception:
                pass

    def get_display_pin(self, bcm_pin: int) -> int:
        return self.BCM_TO_PHYS.get(bcm_pin, bcm_pin)

    async def on_button_pressed(self,event):
        if event.button.id=="btn_gpio":
            if self.gpio_task is None or self.gpio_task.done():
                self.gpio_task = asyncio.create_task(self.scan_gpio()); event.button.label="Stop GPIO"
            else:
                self.gpio_task.cancel(); event.button.label="Scan GPIO"; self.status_text="GPIO scan stopped"
        elif event.button.id=="btn_i2c":
            if self.i2c_task is None or self.i2c_task.done():
                self.i2c_task = asyncio.create_task(self.scan_i2c()); event.button.label="Stop I2C"
            else:
                self.i2c_task.cancel(); event.button.label="Scan I2C"; self.status_text="I2C scan stopped"
        elif event.button.id=="btn_scan_selected":
            row_key = self.last_row_key
            if row_key is not None:
                try:
                    row = self.table.get_row(row_key); bcm_str = row[1] if len(row) > 1 else ""; bcm_pin = int(bcm_str) if str(bcm_str).isdigit() else None
                    if bcm_pin is not None and bcm_pin not in BUS_PINS:
                        if self.gpio_task and not self.gpio_task.done(): self.gpio_task.cancel()
                        self.gpio_task = asyncio.create_task(self.scan_pin(bcm_pin)); self.status_text = f"Safe scan selected BCM {bcm_pin}"
                except Exception: pass
        elif event.button.id=="btn_stop_all":
            stopped=False
            if self.gpio_task and not self.gpio_task.done(): self.gpio_task.cancel(); self.btn_gpio.label="Scan GPIO"; stopped=True
            if self.i2c_task and not self.i2c_task.done(): self.i2c_task.cancel(); self.btn_i2c.label="Scan I2C"; stopped=True
            self.status_text="All scans stopped" if stopped else "No scans running"
        elif event.button.id=="btn_refresh_summary":
            try:
                self.summary_widget.update("[yellow]Loading pin summary...[/yellow]")
            except Exception:
                pass
            try:
                asyncio.create_task(self.update_pin_summary())
            except Exception:
                self.status_text = "Failed to start pin summary task"

    async def _show_row_details(self, row_key):
        try: row = self.table.get_row(row_key)
        except Exception: return
        try: phys_pin = int(row[0])
        except Exception: self.detail_widget.update("Invalid row"); return
        bcm_str = row[1] if len(row) > 1 else ""; bcm_pin = int(bcm_str) if str(bcm_str).isdigit() else None
        sensor_raw = row[5] if len(row) > 5 else ""; info = row[6] if len(row) > 6 else ""; sensor = re.sub(r'\[/?\w+\]', '', sensor_raw).strip()
        if sensor == "" or sensor == "-": self.detail_widget.update(f"Pin {phys_pin}: No sensor detected"); return
        plugin = self.gpio_plugins.get(sensor)
        if plugin is not None and hasattr(plugin, "details"):
            try:
                details_txt = await plugin.details(phys_pin, bcm_pin, self.plugin_ctx); self.detail_widget.update(details_txt); return
            except Exception: pass
        info_clean = re.sub(r'\[/?\w+\]', '', info); level = row[4] if len(row) > 4 else ""; level_clean = re.sub(r'\[/?\w+\]', '', level)
        details = f"Pin {phys_pin}\nSensor: {sensor}\nInfo: {info_clean}\nCurrent level: {level_clean}"; self.detail_widget.update(details)

    async def scan_pin(self, pin:int):
        self.detail_widget.update(f"Searching sensors on pin {pin}...")
        for name, plugin in self.gpio_plugins.items():
            if not getattr(plugin, "auto_detectable", False): continue
            try:
                self.detail_widget.update(f"Pin {pin}: Check {name}..."); self._set_scan_marker(pin, f"Scan {name}")
                res = await asyncio.wait_for(plugin.detect(pin, self.plugin_ctx), timeout=SCAN_PLUGIN_TIMEOUT)
                if res:
                    sensor_type, info, color = res; self._set_sensor_result(pin, sensor_type, info, color); self.detail_widget.update(f"Pin {pin}: {sensor_type} detected – {info}"); return
            except asyncio.TimeoutError: continue
            except Exception: continue
        self._set_scan_marker(pin, "-", color="red"); self.detail_widget.update(f"Pin {pin}: No known sensor found")

    async def poll_sensors_periodically(self, interval: float = 10.0):
        try:
            try:
                if GPIO.getmode() is None: GPIO.setmode(GPIO.BCM)
            except Exception: pass
            while True:
                for pin, sensor in list(self.fixed_pin_sensors.items()):
                    try:
                        plugin = self.gpio_plugins.get(sensor)
                        if plugin is not None:
                            res = await plugin.read(pin, self.plugin_ctx)
                            if res:
                                sensor_type, info, color = res; disp = self.get_display_pin(pin); self.table.update_sensor(disp, sensor_type, info, color=color)
                        elif sensor == "I2C":
                            self.table.update_sensor(pin, "I2C", "active", color="yellow")
                    except Exception: pass
                await asyncio.sleep(SCAN_PIN_DELAY)
                try: self.table.refresh()
                except Exception: pass
                await asyncio.sleep(interval)
        except asyncio.CancelledError: return

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        self.last_row_key = event.row_key; await self._show_row_details(event.row_key)
    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        self.last_row_key = event.row_key; await self._show_row_details(event.row_key)
    async def on_data_table_cell_selected(self, event: DataTable.CellSelected):
        row_key = getattr(event, "row_key", None)
        if row_key is None:
            coord = getattr(event, "coordinate", None)
            if coord is not None:
                row_key = coord.row_key if hasattr(coord, "row_key") else coord.row
        if row_key is not None:
            self.last_row_key = row_key; await self._show_row_details(row_key)

    def on_select_changed(self, event: Select.Changed):
        try:
            value = event.value
            if not value: return
            row_key = self.last_row_key
            if row_key is None: return
            try: row = self.table.get_row(row_key)
            except Exception: return
            try: phys_pin = int(row[0])
            except Exception: return
            bcm_str = row[1] if len(row) > 1 else ""; bcm_pin = int(bcm_str) if str(bcm_str).isdigit() else None
            if bcm_pin is None: return
            self.fixed_pin_sensors[bcm_pin] = value; self.table.update_sensor(phys_pin, value, "manual", color="cyan"); self.status_text = f"Assigned {value} to pin BCM {bcm_pin}"
        except Exception: pass

    async def scan_gpio(self):
        self.status_text="GPIO scan (safe) started"
        try:
            if GPIO.getmode() is None: GPIO.setmode(GPIO.BCM)
        except Exception: pass
        try:
            if self.sensor_poll_task and not self.sensor_poll_task.done(): self.sensor_poll_task.cancel(); self.sensor_poll_task = None
            for pin in range(2,28):
                if pin in BUS_PINS: continue
                if pin in self.fixed_pin_sensors: continue
                found_any = False; await asyncio.sleep(SCAN_PIN_DELAY)
                for name, plugin in self.gpio_plugins.items():
                    if not getattr(plugin, "auto_detectable", False): continue
                    try:
                        self._set_scan_marker(pin, f"Scan {name}")
                        async with self.gpio_sem:
                            res = await asyncio.wait_for(plugin.detect(pin, self.plugin_ctx), timeout=SCAN_PLUGIN_TIMEOUT)
                        if res:
                            sensor_type, info, color = res; self._set_sensor_result(pin, sensor_type, info, color); found_any = True; break
                    except asyncio.TimeoutError:
                        self._set_scan_marker(pin, f"Timeout {name}", color="red"); continue
                    except Exception: continue
                if not found_any: self._set_scan_marker(pin, "-", color="red")
        except asyncio.CancelledError: return
        self.status_text="GPIO scan (safe) finished"; self.btn_gpio.label="Scan GPIO"
        if self.sensor_poll_task is None or self.sensor_poll_task.done(): self.sensor_poll_task = asyncio.create_task(self.poll_sensors_periodically())

    async def scan_i2c(self):
        if not HAS_SMBUS: self.status_text="I2C bus not available"; return
        try:
            bus=smbus.SMBus(1)
        except Exception:
            self.status_text="Error opening I2C bus"; return
        self.status_text="I2C scan started"
        try:
            for addr in range(3,0x78):
                def try_write():
                    try: bus.write_quick(addr); return True
                    except Exception: return False
                found = await asyncio.to_thread(try_write)
                if found: self.table.update_sensor(2,"I2C",f"Addr 0x{addr:02X}",color="yellow")
                self.status_text=f"I2C scan: checking 0x{addr:02X}"; await asyncio.sleep(I2C_SCAN_DELAY)
        except asyncio.CancelledError: return
        self.status_text="I2C scan finished"; self.btn_i2c.label="Scan I2C"


def run_app():
    try:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    except Exception:
        pass
    if os.environ.get("SENSOR_PLUGINS_DIR"):
        print(f"[startup] SENSOR_PLUGINS_DIR={os.environ.get('SENSOR_PLUGINS_DIR')}", flush=True)
    app = GPIOApp()
    print(f"[startup] Total plugins loaded: {len(app.gpio_plugins)}", flush=True)
    # Write Textual logs to a file for diagnostics if supported
    try:
        app.run(log="textual.log")
    except TypeError:
        app.run()
