"""
GPIO Sensor plugin base API.

Plugins must expose a callable `get_plugin()` that returns an instance with:

- attribute `name: str`
- async `detect(pin: int, ctx) -> Optional[tuple[str, str, str]]`
- async `read(pin: int, ctx) -> Optional[tuple[str, str, str]]`
- async `details(phys_pin: int, bcm_pin: int | None, ctx) -> str`

Returned tuple is `(sensor_type, info, color)` where:
- `sensor_type`: short display name (e.g., "DHT22")
- `info`: concise reading/state (e.g., "23.1°C / 45.2%" or "BRIGHT")
- `color`: textual color token (e.g., "green", "cyan", "yellow")

`ctx` provides:
- `ctx.GPIO`: the RPi.GPIO module
- `ctx.gpio_sem`: an asyncio.Semaphore to serialize GPIO access
"""

from typing import Optional, Tuple, Protocol, runtime_checkable


Result = Tuple[str, str, str]


@runtime_checkable
class GPIOSensorPlugin(Protocol):
    name: str

    async def detect(self, pin: int, ctx) -> Optional[Result]:
        ...

    async def read(self, pin: int, ctx) -> Optional[Result]:
        ...

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        ...
