import asyncio


class ButtonPlugin:
    name = "Button"
    bus_type = "GPIO"
    pin_roles: list[str] = ["DATA"]
    auto_detectable = False

    async def detect(self, pin: int, ctx):
        try:
            async with ctx.gpio_sem:
                ctx.GPIO.setup(pin, ctx.GPIO.IN, pull_up_down=ctx.GPIO.PUD_UP)
                v1 = ctx.GPIO.input(pin)
            await asyncio.sleep(0.02)
            async with ctx.gpio_sem:
                v2 = ctx.GPIO.input(pin)
            if v1 == v2:
                state = "PRESSED" if v1 == 0 else "RELEASED"
                return (self.name, state, "magenta")
        except Exception:
            return None
        return None

    async def read(self, pin: int, ctx):
        try:
            async with ctx.gpio_sem:
                ctx.GPIO.setup(pin, ctx.GPIO.IN, pull_up_down=ctx.GPIO.PUD_UP)
                v = ctx.GPIO.input(pin)
            state = "PRESSED" if v == 0 else "RELEASED"
            return (self.name, state, "magenta")
        except Exception:
            return None

    async def read_with_roles(self, roles: dict[str, int], ctx):
        data_pin = roles.get("DATA")
        if data_pin is None:
            return None
        return await self.read(data_pin, ctx)

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        header = f"Pin {phys_pin}"
        try:
            assigned = getattr(ctx, "role_pin_assignments", {}).get((self.name, "DATA"))
            if assigned is not None:
                bcm_pin = assigned
        except Exception:
            pass
        try:
            if bcm_pin is not None:
                res = await self.read(bcm_pin, ctx)
                if res:
                    _, info, _ = res
                    return f"{header}\nSensor: {self.name}\n{info}"
        except Exception:
            pass
        return f"{header}\nSensor: {self.name}\nState: unknown"


def get_plugin():
    return ButtonPlugin()
