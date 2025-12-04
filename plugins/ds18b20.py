import asyncio
from pathlib import Path


class DS18B20Plugin:
    name = "DS18B20"
    auto_detectable = True
    bus_type = "GPIO"
    pin_roles: list[str] = ["DATA"]

    def _read_sysfs(self, device_path: Path):
        try:
            text = device_path.joinpath("w1_slave").read_text(encoding="utf-8")
            if "YES" in text:
                # line2: ... t=23125
                for part in text.split():
                    if part.startswith("t="):
                        milli = int(part[2:])
                        return milli / 1000.0
        except Exception:
            return None
        return None

    async def detect(self, pin: int, ctx):
        # DS18B20 is 1-Wire; usually enabled on GPIO4 (BCM4) and visible via sysfs
        # We try detection only if pin == 4 to avoid false positives
        if pin != 4:
            return None
        base = Path("/sys/bus/w1/devices")
        devices = []
        try:
            if base.exists():
                devices = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("28-")]
        except Exception:
            devices = []
        if not devices:
            return None
        # Try first device
        temp = await asyncio.to_thread(self._read_sysfs, devices[0])
        if temp is not None and -55.0 <= temp <= 125.0:
            return (self.name, f"{temp:.1f}°C", "green")
        return None

    async def read(self, pin: int, ctx):
        base = Path("/sys/bus/w1/devices")
        devices = []
        try:
            if base.exists():
                devices = [p for p in base.iterdir() if p.is_dir() and p.name.startswith("28-")]
        except Exception:
            devices = []
        if not devices:
            return None
        temp = await asyncio.to_thread(self._read_sysfs, devices[0])
        if temp is not None and -55.0 <= temp <= 125.0:
            return (self.name, f"{temp:.1f}°C", "green")
        return None

    async def read_with_roles(self, roles: dict[str, int], ctx):
        # DS18B20 read is independent from the passed pin, but prefer assigned DATA role for clarity
        return await self.read(roles.get("DATA", 4), ctx)

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
            res = await self.read(bcm_pin or 4, ctx)  # DS18B20 commonly on BCM4
            if res:
                _, info, _ = res
                return f"{header}\nSensor: {self.name}\n{info}"
        except Exception:
            pass
        return f"{header}\nSensor: {self.name}\nReading failed or unavailable"


def get_plugin():
    return DS18B20Plugin()
