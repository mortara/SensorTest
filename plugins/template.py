import asyncio

class MySensorPlugin:
    name = "MySensor"
    bus_type = "GPIO"
    pin_roles: list[str] = ["DATA"]
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

    async def read_with_roles(self, roles: dict[str,int], ctx):
        # Example usage for multi-pin plugins: fetch the DATA role
        data_pin = roles.get("DATA")
        if data_pin is None:
            return None
        return await self.read(data_pin, ctx)

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        header = f"Pin {phys_pin}"
        # Example: use role-pin assignments when available
        try:
            role_map = getattr(ctx, "role_pin_assignments", {})
            assigned_data_pin = role_map.get((self.name, "DATA"))
            if assigned_data_pin is not None:
                bcm_pin = assigned_data_pin
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
        return f"{header}\nSensor: {self.name}\nReading unavailable"


def get_plugin():
    return MySensorPlugin()
