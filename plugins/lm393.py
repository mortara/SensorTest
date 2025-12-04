import asyncio


class LM393Plugin:
    name = "LM393"
    bus_type = "GPIO"
    pin_roles: list[str] = ["DATA"]
    auto_detectable = False
    
    async def detect(self, pin: int, ctx):
        # Simple digital light sensor detection by stable level
        try:
            async with ctx.gpio_sem:
                ctx.GPIO.setup(pin, ctx.GPIO.IN)
                v1 = ctx.GPIO.input(pin)
            await asyncio.sleep(0.02)
            async with ctx.gpio_sem:
                v2 = ctx.GPIO.input(pin)
            if v1 == v2:
                state = "BRIGHT" if v1 else "DARK"
                return (self.name, state, "cyan")
        except Exception:
            return None
        return None

    async def read(self, pin: int, ctx):
        try:
            async with ctx.gpio_sem:
                ctx.GPIO.setup(pin, ctx.GPIO.IN)
                v = ctx.GPIO.input(pin)
            state = "BRIGHT" if v else "DARK"
            return (self.name, state, "cyan")
        except Exception:
            return None

    async def read_with_roles(self, roles: dict[str, int], ctx):
        data_pin = roles.get("DATA")
        if data_pin is None:
            return None
        return await self.read(data_pin, ctx)

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        header = f"Pin {phys_pin}"
        # Prefer assigned DATA role
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
                    return f"{header}\nSensor: {self.name}\nState: {info}"
        except Exception:
            pass
        return f"{header}\nSensor: {self.name}\nState: unknown"


def get_plugin():
    return LM393Plugin()
