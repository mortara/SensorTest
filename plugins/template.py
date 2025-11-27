import asyncio

class MySensorPlugin:
    name = "MySensor"
    auto_detectable = False

    async def detect(self, pin: int, ctx):
        # Optional quick detection logic; return None if not detected
        try:
            async with ctx.gpio_sem:
                ctx.GPIO.setup(pin, ctx.GPIO.IN)
                value = ctx.GPIO.input(pin)
            return (self.name, f"value={value}", "blue")
        except Exception:
            return None

    async def read(self, pin: int, ctx):
        # Return a concise reading or state
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


def get_plugin():
    return MySensorPlugin()
