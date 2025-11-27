from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Button, Select
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
import RPi.GPIO as GPIO
import asyncio
import re
import subprocess
from pathlib import Path
import importlib.util
import pkgutil
import importlib
import sys
import os
import logging

# Scan tuning constants
SCAN_PLUGIN_TIMEOUT = 0.5  # seconds per plugin detect
SCAN_PIN_DELAY = 0.1       # delay between pins during GPIO scan
I2C_SCAN_DELAY = 0.05      # delay between I2C addresses

# SMBus for I2C
try:
    import smbus
    HAS_SMBUS = True
except:
    HAS_SMBUS = False

GPIO.setmode(GPIO.BCM)
PIN_MAP = {2:"I2C SDA",3:"I2C SCL",14:"UART TX",15:"UART RX",
           10:"SPI MOSI",9:"SPI MISO",11:"SPI SCLK",8:"SPI CE0",7:"SPI CE1"}
BUS_PINS = set(PIN_MAP.keys())

# -------------------------------------------------------------------
class PinTable(DataTable):
    def __init__(self):
        super().__init__()
        self.pin_to_row = {}
        # Add columns and store keys
        self.col_pin = self.add_column("Pin", width=6)
        self.col_hw = self.add_column("HW Function", width=15)
        self.col_boardfunc = self.add_column("Board Function", width=15)
        self.col_mode = self.add_column("GPIO Mode", width=12)
        self.col_level = self.add_column("Level", width=8)
        self.col_sensor = self.add_column("Sensor", width=18)
        self.col_info = self.add_column("Info", width=25)
        # Rows are created by GPIOApp.build_table_rows()

    def update_sensor(self,pin_display,sensor_type,info,color="green"):
        row_key = self.pin_to_row.get(pin_display)
        if row_key is None:
            return
        # Update specifically via known column keys
        try:
            self.update_cell(row_key, self.col_sensor, f"[{color}]{sensor_type}[/{color}]")
        except Exception:
            pass
        try:
            self.update_cell(row_key, self.col_info, f"[{color}]{info}[/{color}]")
        except Exception:
            pass
        # Visually refresh
        try:
            self.refresh()
        except Exception:
            pass

# -------------------------------------------------------------------
class GPIOApp(App):
    CSS = """
    /* Layout root */
    Screen {layout: vertical;}

    /* Top control bar */
    #buttons {border: round yellow; padding: 1; height: auto;}
    #buttons Button {border: round yellow; padding: 0 1; margin: 0 1;}

    /* Top info row: summary (left) + status+details (right) */
    #topinfo {height: 10; min-height:3;}
    #summary {border: round cyan; padding: 1; width: 1fr; height: 1fr; overflow: auto;}
    #right {height: 1fr;}
    #status {padding: 1; height: 3;}
    #details {border: round yellow; padding: 1; width: 1fr; height: 1fr; min-height:3; overflow: auto;}

    /* Main table */
    #table {border: round green; padding: 1; height: 1fr;}

    /* Sensor manual assignment select */
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
        # Single semaphore to serialize ALL GPIO accesses across the app
        self.gpio_sem = asyncio.Semaphore(1)
        # Toggle auto-detection for unassigned pins
        self.auto_detect_enabled = True
        # Pin numbering mode and mapping
        self.numbering_mode = "BCM"
        self.PHYS_TO_BCM = {
            3: 2, 5: 3, 7: 4, 8: 14, 10: 15, 11: 17, 12: 18, 13: 27, 15: 22,
            16: 23, 18: 24, 19: 10, 21: 9, 22: 25, 23: 11, 24: 8, 26: 7,
            29: 5, 31: 6, 32: 12, 33: 13, 35: 19, 36: 16, 37: 26, 38: 20, 40: 21
        }
        # Non-GPIO pins (power/GND) for BOARD view
        self.NON_GPIO_HW = {
            1: "3V3", 2: "5V", 4: "5V", 6: "GND", 9: "GND", 17: "3V3",
            20: "GND", 25: "GND", 30: "GND", 34: "GND", 39: "GND"
        }
        # Reverse mapping BCM -> PHYS
        self.BCM_TO_PHYS = {bcm: phys for phys, bcm in self.PHYS_TO_BCM.items()}
        # Plugin system for GPIO sensors
        self.gpio_plugins = {}
        print("[startup] Lade Plugins...")
        self._load_gpio_plugins()
        print(f"[startup] Plugins geladen: {', '.join(sorted(self.gpio_plugins.keys())) if self.gpio_plugins else 'keine'}")
        # Simple context to pass to plugins
        class _PluginCtx:
            def __init__(self, gpio, sem):
                self.GPIO = gpio
                self.gpio_sem = sem
        self.plugin_ctx = _PluginCtx(GPIO, self.gpio_sem)

    # ----------------- Helpers -----------------
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

        # Buttons als Attribute anlegen, damit sie später referenziert werden können
        self.btn_gpio = Button("Start GPIO Scan", id="btn_gpio")
        self.btn_i2c = Button("Start I2C Scan", id="btn_i2c")
        self.btn_stop_all = Button("Stop All Scans", id="btn_stop_all")
        self.btn_scan_selected = Button("Scan Selected Pin", id="btn_scan_selected")
        self.btn_refresh = Button("Refresh Summary & Table", id="btn_refresh")


        # Sensor selection (combobox) — options from plugins + I2C
        plugin_options = self._build_plugin_options()
        self.sensor_select = Select(
            options=plugin_options,
            allow_blank=True,
            prompt="Assign sensor to selected pin",
            id="sensor_select"
        )

        # Buttons and selects in a horizontal container
        yield Horizontal(
            self.btn_gpio,
            self.btn_i2c,
            self.btn_stop_all,
            self.btn_refresh,
            self.sensor_select,
            self.btn_scan_selected,
            id="buttons"
        )

        # Table
        self.table = PinTable()
        self.table.id = "table"

        # Try to enable table cursor/row selection (compatible)
        try:
            self.table.cursor_type = "row"
            self.table.show_cursor = True
        except Exception:
            pass

        # Summary and details side-by-side above table
        self.summary_widget = Static("", id="summary")
        self.status_widget = Static("", id="status")
        self.detail_widget = Static("", id="details")
        right_side = Vertical(self.status_widget, self.detail_widget, id="right")
        yield Horizontal(self.summary_widget, right_side, id="topinfo")
        # Initial table population
        self.build_table_rows()
        # Add table below topinfo
        yield self.table

        yield Footer()

    def watch_status_text(self,value:str):
        try:
            if hasattr(self, "status_widget") and self.status_widget is not None:
                self.status_widget.update(f"[yellow]{value}[/yellow]")
        except Exception:
            pass

    async def on_mount(self):
        # Ensure the selection reflects currently loaded plugins
        try:
            if hasattr(self, "sensor_select"):
                self.sensor_select.set_options(self._build_plugin_options())
        except Exception:
            pass
        # Start periodic sensor polling
        if self.sensor_poll_task is None or self.sensor_poll_task.done():
            self.sensor_poll_task = asyncio.create_task(self.poll_sensors_periodically())
        # Update pintest summary
        asyncio.create_task(self.update_pintest_summary())

    async def on_unmount(self):
        # Gracefully stop task
        if self.sensor_poll_task and not self.sensor_poll_task.done():
            self.sensor_poll_task.cancel()

    async def update_pintest_summary(self):
        # Run 'pintest' (WiringPi) or fallback to 'gpio readall' / 'pinout' and show a concise summary
        def try_cmd(cmd:list[str]):
            try:
                return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
            except Exception:
                return None

        output = await asyncio.to_thread(try_cmd, ["pintest"])  # WiringPi test (deprecated on newer Pi OS)
        title = "pintest"
        if not output:
            output = await asyncio.to_thread(try_cmd, ["pinout"])  # Raspberry Pi pin summary
            title = "pinout"

        if output:
            lines = [ln for ln in output.splitlines() if ln.strip()]
            summary = "\n".join(lines[:12]) if lines else "No output"
            self.summary_widget.update(f"[cyan]{title} summary:[/cyan]\n{summary}")
            self.status_text = f"Using {title} for pin info"
        else:
            self.summary_widget.update("No pintest/pinout available or failed")
            self.status_text = "No pin info source available"

    def build_table_rows(self):
        # Clear and repopulate table using system-reported pin layout (BOARD with BCM column)
        try:
            self.table.clear()
            self.table.pin_to_row.clear()
        except Exception:
            pass
        pins = self.get_system_pin_info()
        if not pins:
            self.status_text = "No pin info from system tools; showing placeholders"
            for phys in range(1,41):
                row_key = self.table.add_row(str(phys), "", "", "N/A", "N/A", "[red]-[/red]", "")
                self.table.pin_to_row[phys] = row_key
            return
        # Build dynamic BCM->PHYS map
        self.BCM_TO_PHYS = {}
        for entry in pins:
            bcm_v = entry.get("bcm")
            if bcm_v is not None:
                self.BCM_TO_PHYS[bcm_v] = entry["phys"]
        # Populate table from pinout
        for entry in pins:
            phys = entry.get("phys")
            bcm = entry.get("bcm")
            board_func = entry.get("name", "")
            # Enhance board function for known BCMs
            if bcm is not None and (board_func == "GPIO" or board_func == ""):
                bcm_map = {
                    2: "I2C SDA",
                    3: "I2C SCL",
                    14: "UART TX",
                    15: "UART RX",
                    10: "SPI MOSI",
                    9: "SPI MISO",
                    11: "SPI SCLK",
                    8: "SPI CE0",
                    7: "SPI CE1",
                }
                board_func = bcm_map.get(bcm, board_func)
            bcm_str = str(bcm) if bcm is not None else ""
            try:
                if bcm is not None:
                    mode = GPIO.gpio_function(bcm)
                    mode_str = "INPUT" if mode==GPIO.IN else "OUTPUT" if mode==GPIO.OUT else f"ALT{mode}"
                    lvl = GPIO.input(bcm)
                    lvl_str = "HIGH" if lvl else "LOW"
                else:
                    mode_str = "N/A"
                    lvl_str = "N/A"
            except Exception:
                mode_str = "N/A"
                lvl_str = "N/A"
            # Enrich Info via gpiozero without changing pin state
            # Keep info concise so it fits narrow columns
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

        # After initial population, try to refresh GPIO mode/level once more
        try:
            self.refresh_gpio_states()
        except Exception:
            pass

    def refresh_gpio_states(self):
        """Refresh GPIO Mode and Level columns for rows with a valid BCM pin.
        Does not change pin configuration; reads current function and level if possible.
        """
        # Init semaphore and scan flag if not present
        if not hasattr(self, "gpio_sem"):
            import asyncio as _asyncio
            self.gpio_sem = _asyncio.Semaphore(1)
        if not hasattr(self, "scanning"):
            self.scanning = False
        # Ensure GPIO mode is set to BCM only if unset
        try:
            if GPIO.getmode() is None:
                GPIO.setmode(GPIO.BCM)
        except Exception:
            return
        # Iterate through table rows and update mode/level
        try:
            # Prevent concurrent GPIO accesses during refresh
            self.scanning = True
            import asyncio as _asyncio
            async def _do_refresh():
                async with self.gpio_sem:
                    for phys, row_key in list(self.table.pin_to_row.items()):
                        try:
                            bcm_cell = self.table.get_cell(row_key, 1)
                            bcm = int(bcm_cell) if str(bcm_cell).isdigit() else None
                            if bcm is None:
                                continue
                            mode = GPIO.gpio_function(bcm)
                            mode_str = "INPUT" if mode==GPIO.IN else "OUTPUT" if mode==GPIO.OUT else f"ALT{mode}"
                            lvl = GPIO.input(bcm)
                            lvl_str = "HIGH" if lvl else "LOW"
                            self.table.update_cell(row_key, 3, mode_str)
                            self.table.update_cell(row_key, 4, lvl_str)
                        except Exception:
                            continue
            # Run a short-lived task to execute the async refresh; if already in an event loop, schedule it
            loop = None
            try:
                loop = _asyncio.get_event_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                loop.create_task(_do_refresh())
            else:
                _asyncio.run(_do_refresh())
        finally:
            self.scanning = False

    def get_system_pin_info(self):
        """Return a list of dicts with keys: phys, bcm, name from 'pinout' output."""
        def try_cmd(cmd:list[str]):
            try:
                return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
            except Exception:
                return None
        out = try_cmd(["pinout"]) or ""
        pins = []
        if not out:
            return pins
        lines = out.splitlines()
        import re as _re
        # Parse J8 block
        j8_index = None
        for idx, ln in enumerate(lines):
            if ln.strip().startswith("J8:"):
                j8_index = idx
                break
        if j8_index is not None:
            for ln in lines[j8_index+1:]:
                if not ln.strip():
                    break
                m = _re.match(r"^\s*(\S+)\s*\((\d+)\)\s*\((\d+)\)\s*(\S+)\s*$", ln)
                if not m:
                    m = _re.match(r"^\s*(\S+)\s*\((\d+)\)\s*\((\d+)\)\s*(.+?)\s*$", ln)
                if m:
                    left_name = m.group(1).strip()
                    left_phys = int(m.group(2))
                    right_phys = int(m.group(3))
                    right_name = m.group(4).strip()
                    def to_entry(name_str, phys):
                        name_up = name_str.upper()
                        bcm = None
                        board_name = name_str
                        if name_up.startswith("GPIO") and name_up[4:].isdigit():
                            bcm = int(name_up[4:])
                            board_name = "GPIO"
                        elif name_up in ("3V3", "3.3V"):
                            board_name = "3V3"
                        elif name_up in ("5V"):
                            board_name = "5V"
                        elif name_up in ("GND", "GROUND"):
                            board_name = "GND"
                        return {"phys": phys, "bcm": bcm, "name": board_name}
                    pins.append(to_entry(left_name, left_phys))
                    pins.append(to_entry(right_name, right_phys))
        # Fallback regex for generic lines
        if not pins:
            for ln in lines:
                m = _re.search(r"GPIO\s*(\d+)\s*(?:\(([^)]+)\))?.*?physical\s*pin\s*(\d+)", ln, _re.IGNORECASE)
                if m:
                    bcm = int(m.group(1))
                    label = (m.group(2) or "").strip()
                    phys = int(m.group(3))
                    label_upper = label.upper()
                    name_map = {
                        "SDA": "I2C SDA",
                        "SDA1": "I2C SDA",
                        "SCL": "I2C SCL",
                        "SCL1": "I2C SCL",
                        "TXD": "UART TX",
                        "RXD": "UART RX",
                        "MOSI": "SPI MOSI",
                        "MISO": "SPI MISO",
                        "SCLK": "SPI SCLK",
                        "SCK": "SPI SCLK",
                        "CE0": "SPI CE0",
                        "CE1": "SPI CE1",
                    }
                    name = name_map.get(label_upper, label) if label else "GPIO"
                    pins.append({"phys": phys, "bcm": bcm, "name": name})
            # Power/GND hints
            for ln in lines:
                m = _re.search(r"(3V3|3\.3V|5V|GND|GROUND).+physical\s*pin\s*(\d+)", ln, _re.IGNORECASE)
                if m:
                    phys = int(m.group(2))
                    name_raw = m.group(1).upper()
                    name = "3V3" if name_raw in ("3.3V", "3V3") else ("GND" if name_raw in ("GND", "GROUND") else name_raw)
                    if all(p.get("phys") != phys for p in pins):
                        pins.append({"phys": phys, "bcm": None, "name": name})
        pins.sort(key=lambda x: x.get("phys", 0))
        return pins

    def get_display_pin(self, bcm_pin: int) -> int:
        # Always return physical pin number (BOARD mode)
        return self.BCM_TO_PHYS.get(bcm_pin, bcm_pin)

    # ----------------- Button Events -----------------
    async def on_button_pressed(self,event):
        if event.button.id=="btn_gpio":
            if self.gpio_task is None or self.gpio_task.done():
                self.gpio_task = asyncio.create_task(self.scan_gpio())
                event.button.label="Stop GPIO Scan"
            else:
                self.gpio_task.cancel()
                event.button.label="Start GPIO Scan"
                self.status_text="GPIO scan stopped"
        elif event.button.id=="btn_i2c":
            if self.i2c_task is None or self.i2c_task.done():
                self.i2c_task = asyncio.create_task(self.scan_i2c())
                event.button.label="Stop I2C Scan"
            else:
                self.i2c_task.cancel()
                event.button.label="Start I2C Scan"
                self.status_text="I2C scan stopped"
        elif event.button.id=="btn_scan_selected":
            # Scan only the currently selected row/pin in safe mode
            row_key = self.last_row_key
            if row_key is not None:
                try:
                    row = self.table.get_row(row_key)
                    bcm_str = row[1] if len(row) > 1 else ""
                    bcm_pin = int(bcm_str) if str(bcm_str).isdigit() else None
                    if bcm_pin is not None and bcm_pin not in BUS_PINS:
                        if self.gpio_task and not self.gpio_task.done():
                            self.gpio_task.cancel()
                        self.gpio_task = asyncio.create_task(self.scan_pin(bcm_pin))
                        self.status_text = f"Safe scan selected BCM {bcm_pin}"
                except Exception:
                    pass
        elif event.button.id=="btn_stop_all":
            stopped=False
            if self.gpio_task and not self.gpio_task.done():
                self.gpio_task.cancel()
                self.btn_gpio.label="Start GPIO Scan"
                stopped=True
            if self.i2c_task and not self.i2c_task.done():
                self.i2c_task.cancel()
                self.btn_i2c.label="Start I2C Scan"
                stopped=True
            self.status_text="All scans stopped" if stopped else "No scans running"
        elif event.button.id=="btn_refresh":
            # Reload plugins and refresh selection list
            try:
                self.gpio_plugins.clear()
                self._load_gpio_plugins()
                if hasattr(self, "sensor_select"):
                    self.sensor_select.set_options(self._build_plugin_options())
            except Exception:
                pass
            await self.update_pintest_summary()
            self.build_table_rows()
            self.status_text = "Summary and table refreshed"
        

# ----------------- Handler: row selection -----------------
    async def _show_row_details(self, row_key):
        # Shared logic for different selection events
        try:
            row = self.table.get_row(row_key)
        except Exception:
            return
        try:
            phys_pin = int(row[0])
        except Exception:
            self.detail_widget.update("Invalid row")
            return

        # Columns: 0 Pin (phys), 1 BCM (string), 2 Board func, 3 Mode, 4 Level, 5 Sensor, 6 Info
        bcm_str = row[1] if len(row) > 1 else ""
        try:
            bcm_pin = int(bcm_str) if str(bcm_str).isdigit() else None
        except Exception:
            bcm_pin = None
        sensor_raw = row[5] if len(row) > 5 else ""
        info = row[6] if len(row) > 6 else ""
        sensor = re.sub(r'\[/?\w+\]', '', sensor_raw).strip()

        if sensor == "" or sensor == "-":
            self.detail_widget.update(f"Pin {phys_pin}: No sensor detected")
            return

        # Delegate full rendering to plugin if available
        plugin = self.gpio_plugins.get(sensor)
        if plugin is not None and hasattr(plugin, "details"):
            try:
                details_txt = await plugin.details(phys_pin, bcm_pin, self.plugin_ctx)
                self.detail_widget.update(details_txt)
                return
            except Exception:
                pass

        # Fallback generic details
        info_clean = re.sub(r'\[/?\w+\]', '', info)
        level = row[4] if len(row) > 4 else ""
        level_clean = re.sub(r'\[/?\w+\]', '', level)
        details = f"Pin {phys_pin}\nSensor: {sensor}\nInfo: {info_clean}\nCurrent level: {level_clean}"
        self.detail_widget.update(details)

    async def scan_pin(self, pin:int):
        self.detail_widget.update(f"Searching sensors on pin {pin}...")

        # Check known sensors via plugins
        for name, plugin in self.gpio_plugins.items():
            if not getattr(plugin, "auto_detectable", False):
                continue
            try:
                self.detail_widget.update(f"Pin {pin}: Check {name}...")
                # Show current plugin being checked in the table
                self._set_scan_marker(pin, f"Scan {name}")
                # Avoid hanging on single-pin scans as well
                res = await asyncio.wait_for(plugin.detect(pin, self.plugin_ctx), timeout=SCAN_PLUGIN_TIMEOUT)
                if res:
                    sensor_type, info, color = res
                    self._set_sensor_result(pin, sensor_type, info, color)
                    self.detail_widget.update(f"Pin {pin}: {sensor_type} detected – {info}")
                    return
            except asyncio.TimeoutError:
                # Move on to next plugin on timeout
                continue
            except Exception:
                continue

        # Falls nichts erkannt wurde
        self._set_scan_marker(pin, "-", color="red")
        self.detail_widget.update(f"Pin {pin}: No known sensor found")

    async def poll_sensors_periodically(self, interval: float = 10.0):
        # Fragt regelmäßig alle bekannten/manuell zugewiesenen Sensoren ab und aktualisiert die Tabelle
        try:
            # Ensure BCM mode for periodic reads
            try:
                if GPIO.getmode() is None:
                    GPIO.setmode(GPIO.BCM)
            except Exception:
                pass
            while True:
                # 1) Manuell zugewiesene Pins bevorzugt lesen
                for pin, sensor in list(self.fixed_pin_sensors.items()):
                    try:
                        plugin = self.gpio_plugins.get(sensor)
                        if plugin is not None:
                            res = await plugin.read(pin, self.plugin_ctx)
                            if res:
                                sensor_type, info, color = res
                                disp = self.get_display_pin(pin)
                                self.table.update_sensor(disp, sensor_type, info, color=color)
                        elif sensor == "I2C":
                            # No per-pin reading; keep info
                            self.table.update_sensor(pin, "I2C", "active", color="yellow")
                    except Exception:
                        pass

                # Kurze Pause zwischen Pins, um CPU-Last zu senken
                await asyncio.sleep(SCAN_PIN_DELAY)

                # Tabelle sichtbar aktualisieren
                try:
                    self.table.refresh()
                except Exception:
                    pass

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return

    # Forward RowSelected handler
    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        self.last_row_key = event.row_key
        await self._show_row_details(event.row_key)

    # If the table fires RowHighlighted instead (e.g., with cursor)
    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        self.last_row_key = event.row_key
        await self._show_row_details(event.row_key)

    async def on_data_table_cell_selected(self, event: DataTable.CellSelected):
        # Many versions also provide row_key in the event
        row_key = getattr(event, "row_key", None)
        if row_key is None:
            coord = getattr(event, "coordinate", None)
            if coord is not None:
                row_key = coord.row_key if hasattr(coord, "row_key") else coord.row
        if row_key is not None:
            self.last_row_key = row_key
            await self._show_row_details(row_key)

    # ----------------- Manual assignment via Select -----------------
    def on_select_changed(self, event: Select.Changed):
        try:
            value = event.value
            if not value:
                return
            # Need a selected row to assign
            row_key = self.last_row_key
            if row_key is None:
                return
            try:
                row = self.table.get_row(row_key)
            except Exception:
                return
            try:
                phys_pin = int(row[0])
            except Exception:
                return
            bcm_str = row[1] if len(row) > 1 else ""
            try:
                bcm_pin = int(bcm_str) if str(bcm_str).isdigit() else None
            except Exception:
                bcm_pin = None
            if bcm_pin is None:
                return
            # Store manual assignment for periodic reads
            self.fixed_pin_sensors[bcm_pin] = value
            # Update table immediately
            self.table.update_sensor(phys_pin, value, "manual", color="cyan")
            self.status_text = f"Assigned {value} to pin BCM {bcm_pin}"
        except Exception:
            pass

    # ----------------- GPIO Scan -----------------
    async def scan_gpio(self):
        self.status_text="GPIO scan (safe) gestartet"
        # Ensure BCM mode is set once before scanning
        try:
            if GPIO.getmode() is None:
                GPIO.setmode(GPIO.BCM)
        except Exception:
            pass
        try:
            # Pause periodic polling during the scan
            if self.sensor_poll_task and not self.sensor_poll_task.done():
                self.sensor_poll_task.cancel()
                self.sensor_poll_task = None
            for pin in range(2,28):
                if pin in BUS_PINS:
                    continue
                # Do not overwrite manually assigned pins
                if pin in self.fixed_pin_sensors:
                    continue
                found_any = False
                await asyncio.sleep(SCAN_PIN_DELAY)
                # Try only plugins that explicitly support safe auto-detection
                for name, plugin in self.gpio_plugins.items():
                    if not getattr(plugin, "auto_detectable", False):
                        continue
                    try:
                        # Show current plugin being checked in the table Sensor column
                        self._set_scan_marker(pin, f"Scan {name}")
                        # Serialize hardware access during detection with a timeout to avoid hanging
                        async with self.gpio_sem:
                            res = await asyncio.wait_for(plugin.detect(pin, self.plugin_ctx), timeout=SCAN_PLUGIN_TIMEOUT)
                        if res:
                            sensor_type, info, color = res
                            self._set_sensor_result(pin, sensor_type, info, color)
                            found_any = True
                            break
                    except asyncio.TimeoutError:
                        # Mark timeout but continue to next plugin
                        self._set_scan_marker(pin, f"Timeout {name}", color="red")
                        continue
                    except Exception:
                        continue
                # If no plugin matched, clear scan marker for this pin
                if not found_any:
                    self._set_scan_marker(pin, "-", color="red")
        except asyncio.CancelledError:
            return
        
        self.status_text="GPIO scan (safe) beendet"
        self.btn_gpio.label="Start GPIO Scan"
        # Restart periodic polling after the scan
        if self.sensor_poll_task is None or self.sensor_poll_task.done():
            self.sensor_poll_task = asyncio.create_task(self.poll_sensors_periodically())

    # ----------------- I2C Scan -----------------
    async def scan_i2c(self):
        if not HAS_SMBUS:
            self.status_text="I2C-Bus nicht verfügbar"
            return
        try:
            bus=smbus.SMBus(1)
        except:
            self.status_text="Fehler beim Öffnen des I2C-Bus"
            return
        self.status_text="I2C-Scan gestartet"
        try:
            for addr in range(3,0x78):
                def try_write():
                    try: bus.write_quick(addr); return True
                    except: return False
                found = await asyncio.to_thread(try_write)
                if found:
                    self.table.update_sensor(2,"I2C",f"Addr 0x{addr:02X}",color="yellow")
                self.status_text=f"I2C scan: checking 0x{addr:02X}"
                await asyncio.sleep(I2C_SCAN_DELAY)
        except asyncio.CancelledError:
            return
        
        self.status_text="I2C-Scan beendet"
        self.btn_i2c.label="Start I2C Scan"

    # ----------------- Plugin loading -----------------
    def _load_gpio_plugins(self):
        try:
            # 1) Candidate directories
            base_dir = Path(__file__).parent
            env_dir = os.environ.get("SENSOR_PLUGINS_DIR")
            candidate_dirs = [base_dir / "plugins", base_dir / "Plugins"]
            if env_dir:
                candidate_dirs.insert(0, Path(env_dir))
            print("[startup] Suche Plugins in:")
            for d in candidate_dirs:
                print(f"  - {d} {'(exists)' if d.exists() else '(missing)'}")

            # 2) Iterate directories and import modules/packages
            for plugins_dir in candidate_dirs:
                if not plugins_dir.exists():
                    continue
                # Ensure import path contains plugins directory
                if str(plugins_dir) not in sys.path:
                    sys.path.insert(0, str(plugins_dir))

                for m_info in pkgutil.iter_modules([str(plugins_dir)]):
                    mod_name = m_info.name
                    # Skip non-plugin infra modules
                    if mod_name in {"__init__", "base"}:
                        continue
                    print(f"[startup] Lade Modul '{mod_name}'...")
                    module = None
                    try:
                        module = importlib.import_module(mod_name)
                    except Exception as e:
                        print(f"[startup] Import fehlgeschlagen: {mod_name}: {e}")
                        # Fallback: compile+exec with future annotations
                        module = self._fallback_load_with_future_annotations(plugins_dir, mod_name)
                    if module is None:
                        continue

                    # 3) Register plugin instances from module
                    get_plugin = getattr(module, "get_plugin", None)
                    if not callable(get_plugin):
                        continue
                    try:
                        instance = get_plugin()
                        name = getattr(instance, "name", None)
                        if not name:
                            continue
                        self.gpio_plugins[name] = instance
                        print(f"[startup] Plugin registriert: {name}")
                        print(f"[startup]  → Auto-Detection: {'aktiviert' if getattr(instance, 'auto_detectable', False) else 'deaktiviert'}")
                    except Exception:
                        continue
        except Exception:
            pass

    def _fallback_load_with_future_annotations(self, plugins_dir: Path, mod_name: str):
        """Best-effort Fallback: lädt ein Plugin-Modul als Datei oder Paket und
        kompiliert mit aktivierten Future-Annotations, damit "X | None" unter Python < 3.10 funktioniert.
        Gibt das geladene Modul zurück oder None bei Fehler.
        """
        try:
            file = plugins_dir / f"{mod_name}.py"
            pkg_init = plugins_dir / mod_name / "__init__.py"
            src_path = None
            is_pkg = False
            if file.exists():
                src_path = file
            elif pkg_init.exists():
                src_path = pkg_init
                is_pkg = True
            else:
                print(f"[startup] Direktladen fehlgeschlagen: {mod_name}: Quelle nicht gefunden")
                return None

            import types, __future__
            code_text = src_path.read_text(encoding="utf-8")
            flags = __future__.annotations.compiler_flag
            code_obj = compile(code_text, str(src_path), "exec", flags=flags, dont_inherit=True)
            module = types.ModuleType(mod_name)
            module.__file__ = str(src_path)
            module.__package__ = mod_name if is_pkg else ""
            if is_pkg:
                module.__path__ = [str(src_path.parent)]  # type: ignore[attr-defined]
            sys.modules[mod_name] = module
            exec(code_obj, module.__dict__)
            print(f"[startup] Fallback geladen mit Future-Annotations: {src_path.name}")
            return module
        except Exception as e2:
            print(f"[startup] Direktladen fehlgeschlagen: {mod_name}: {e2}")
            return None

    def _build_plugin_options(self):
        try:
            opts = [(name, name) for name in sorted(self.gpio_plugins.keys())]
        except Exception:
            opts = []
        # Always provide I2C manual assignment option
        opts.append(("I2C Device", "I2C"))
        return opts

# -------------------------------------------------------------------
if __name__=="__main__":
        try:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        except Exception:
            pass
        print("[startup] Starte SensorTest UI...")
        if os.environ.get("SENSOR_PLUGINS_DIR"):
            print(f"[startup] SENSOR_PLUGINS_DIR={os.environ.get('SENSOR_PLUGINS_DIR')}")
        app = GPIOApp()
        print(f"[startup] Insgesamt geladene Plugins: {len(app.gpio_plugins)}")
        app.run()
