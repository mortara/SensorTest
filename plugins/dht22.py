import asyncio

try:
    import Adafruit_DHT
    HAS_ADAFRUIT = True
except Exception:
    HAS_ADAFRUIT = False


class DHT22Plugin:
    name = "DHT22"
    auto_detectable = True

    async def detect(self, pin: int, ctx):
        if not HAS_ADAFRUIT:
            return None
        # Try a couple of reads; consider valid if within plausible ranges
        def _read():
            return Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, pin, retries=3, delay_seconds=0.4)

        try:
            async with ctx.gpio_sem:
                humidity, temp = await asyncio.to_thread(_read)
            if humidity is not None and temp is not None and 0 <= humidity <= 100 and -40 <= temp <= 80:
                return (self.name, f"{temp:.1f}°C / {humidity:.1f}%", "green")
        except Exception:
            return None
        return None

    async def read(self, pin: int, ctx):
        if not HAS_ADAFRUIT:
            return None
        def _read():
            return Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, pin, retries=2, delay_seconds=0.5)

        try:
            async with ctx.gpio_sem:
                humidity, temp = await asyncio.to_thread(_read)
            if humidity is not None and temp is not None and 0 <= humidity <= 100 and -40 <= temp <= 80:
                return (self.name, f"{temp:.1f}°C / {humidity:.1f}%", "green")
        except Exception:
            return None
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
        return f"{header}\nSensor: {self.name}\nReading failed or unavailable"


def get_plugin():
    return DHT22Plugin()
