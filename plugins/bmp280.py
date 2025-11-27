import asyncio

try:
    # Preferred lightweight library: pip install bmp280
    from bmp280 import BMP280
    HAS_BMP280_LIB = True
except Exception:
    HAS_BMP280_LIB = False

try:
    # Fallback Adafruit library
    import Adafruit_BMP.BMP280 as Adafruit_BMP280
    HAS_ADAFRUIT_BMP = True
except Exception:
    HAS_ADAFRUIT_BMP = False

try:
    import smbus
    HAS_SMBUS = True
except Exception:
    HAS_SMBUS = False


class BMP280Plugin:
    name = "BMP280"

    def _detect_address(self):
        if not HAS_SMBUS:
            return None
        try:
            bus = smbus.SMBus(1)
        except Exception:
            return None
        for addr in (0x76, 0x77):
            try:
                bus.write_quick(addr)
                return addr
            except Exception:
                continue
        return None

    async def detect(self, pin: int, ctx):
        # BMP280 is I2C; detection independent of GPIO pin but we surface via plugins
        addr = await asyncio.to_thread(self._detect_address)
        if addr is None:
            return None
        # If libraries are available, try a quick read
        try:
            if HAS_BMP280_LIB and HAS_SMBUS:
                bus = smbus.SMBus(1)
                sensor = BMP280(i2c_dev=bus, i2c_addr=addr)
                temp = sensor.get_temperature()
                pressure = sensor.get_pressure()
                return (self.name, f"{temp:.1f}°C / {pressure:.0f} hPa", "yellow")
            elif HAS_ADAFRUIT_BMP:
                sensor = Adafruit_BMP280.BMP280()
                temp = sensor.read_temperature()
                pressure = sensor.read_pressure() / 100.0
                return (self.name, f"{temp:.1f}°C / {pressure:.0f} hPa", "yellow")
        except Exception:
            # Detection still succeeded; report address only
            return (self.name, f"Addr 0x{addr:02X}", "yellow")
        # If we get here, just report address
        return (self.name, f"Addr 0x{addr:02X}", "yellow")

    async def read(self, pin: int, ctx):
        addr = await asyncio.to_thread(self._detect_address)
        if addr is None:
            return None
        try:
            if HAS_BMP280_LIB and HAS_SMBUS:
                bus = smbus.SMBus(1)
                sensor = BMP280(i2c_dev=bus, i2c_addr=addr)
                temp = sensor.get_temperature()
                pressure = sensor.get_pressure()
                return (self.name, f"{temp:.1f}°C / {pressure:.0f} hPa", "yellow")
            elif HAS_ADAFRUIT_BMP:
                sensor = Adafruit_BMP280.BMP280()
                temp = sensor.read_temperature()
                pressure = sensor.read_pressure() / 100.0
                return (self.name, f"{temp:.1f}°C / {pressure:.0f} hPa", "yellow")
        except Exception:
            return (self.name, f"Addr 0x{addr:02X}", "yellow")
        return (self.name, f"Addr 0x{addr:02X}", "yellow")

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        header = f"Pin {phys_pin}"
        try:
            res = await self.read(bcm_pin or 0, ctx)
            if res:
                _, info, _ = res
                return f"{header}\nSensor: {self.name}\n{info}"
        except Exception:
            pass
        return f"{header}\nSensor: {self.name}\nReading failed or unavailable"


def get_plugin():
    return BMP280Plugin()
