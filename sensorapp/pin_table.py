from textual.widgets import DataTable

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

    def update_sensor(self, pin_display, sensor_type, info, color="green"):
        row_key = self.pin_to_row.get(pin_display)
        if row_key is None:
            return
        try:
            self.update_cell(row_key, self.col_sensor, f"[{color}]{sensor_type}[/{color}]")
        except Exception:
            pass
        try:
            self.update_cell(row_key, self.col_info, f"[{color}]{info}[/{color}]")
        except Exception:
            pass
        try:
            self.refresh()
        except Exception:
            pass
