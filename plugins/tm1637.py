import asyncio

class TM1637Plugin:
    name = "TM1637"
    pin_roles = ["CLK", "DIO"]
    auto_detectable = False  # requires two pins (CLK, DIO), manual assignment

    def __init__(self):
        self._last_message = None

    async def detect(self, pin: int, ctx):
        # Not auto-detectable in single-pin model
        return None

    async def read(self, pin: int, ctx):
        # No single-pin read semantics; return last message if any
        if self._last_message:
            return (self.name, self._last_message, "yellow")
        return None

    async def read_with_roles(self, roles: dict[str, int], ctx):
        clk = roles.get("CLK")
        dio = roles.get("DIO")
        if clk is None or dio is None:
            return None
        msg = await self._display_time(clk, dio)
        self._last_message = msg
        return (self.name, msg, "yellow")

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        header = f"Pin {phys_pin}"
        # Prefer assigned role pins via ctx.role_pin_assignments
        clk = None
        dio = None
        try:
            role_map = getattr(ctx, "role_pin_assignments", {})
            clk = role_map.get((self.name, "CLK"))
            dio = role_map.get((self.name, "DIO"))
        except Exception:
            pass
        # Fallback: environment variables if no assignment exists
        if clk is None or dio is None:
            try:
                import os
                env_clk = os.getenv("TM1637_CLK_PIN")
                env_dio = os.getenv("TM1637_DIO_PIN")
                if clk is None:
                    clk = int(env_clk) if env_clk and str(env_clk).isdigit() else None
                if dio is None:
                    dio = int(env_dio) if env_dio and str(env_dio).isdigit() else None
            except Exception:
                pass

        if clk is not None and dio is not None:
            try:
                # minimal demo: display the current time HH:MM
                res = await self.read_with_roles({"CLK": clk, "DIO": dio}, ctx)
                msg = res[1] if res else ""
                return f"{header}\nSensor: {self.name}\nCLK={clk} DIO={dio}\n{msg}"
            except Exception as e:
                return f"{header}\nSensor: {self.name}\nCLK={clk} DIO={dio}\nDisplay error: {e}"
        else:
            tip = (
                f"{header}\nSensor: {self.name}\n"
                "This module needs two BCM pins (CLK and DIO).\n"
                "Assign roles via the select as 'TM1637:CLK' and 'TM1637:DIO' to pins,\n"
                "or set environment variables TM1637_CLK_PIN and TM1637_DIO_PIN.\n"
                "Example env: TM1637_CLK_PIN=23 TM1637_DIO_PIN=24"
            )
            return tip

    async def _display_time(self, clk_bcm: int, dio_bcm: int) -> str:
        # Run blocking I/O in a thread to avoid blocking the event loop
        def work():
            try:
                import tm1637
                import time
                display = tm1637.TM1637(clk=clk_bcm, dio=dio_bcm)
                display.brightness(3)
                # Show HH:MM
                hh = time.localtime().tm_hour
                mm = time.localtime().tm_min
                display.numbers(hh, mm)
                return f"Displayed time {hh:02d}:{mm:02d}"
            except Exception as e:
                raise e
        return await asyncio.to_thread(work)


def get_plugin():
    return TM1637Plugin()
