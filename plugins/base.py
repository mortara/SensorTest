"""
GPIO Sensor plugin base API.

Plugins must expose a callable `get_plugin()` that returns an instance with:

- attribute `name: str`
- optional attribute `bus_type: str` (e.g., "GPIO", "I2C", "SPI")
- optional attribute `pin_roles: list[str]` for multi-pin sensors (e.g., ["CLK","DIO"]).
- attribute `auto_detectable: bool` (participates in safe auto-discovery)
- async `detect(pin: int, ctx) -> Optional[tuple[str, str, str]]`
- async `read(pin: int, ctx) -> Optional[tuple[str, str, str]]`
- async `details(phys_pin: int, bcm_pin: int | None, ctx) -> str`

Optional for multi-pin devices:
- async `detect_with_roles(roles: dict[str,int], ctx) -> Optional[tuple[str,str,str]]`
- async `read_with_roles(roles: dict[str,int], ctx) -> Optional[tuple[str,str,str]]`

Returned tuple is `(sensor_type, info, color)` where:
- `sensor_type`: short display name (e.g., "DHT22")
- `info`: concise reading/state (e.g., "23.1°C / 45.2%" or "BRIGHT")
- `color`: textual color token (e.g., "green", "cyan", "yellow")

`ctx` provides:
- `ctx.GPIO`: the RPi.GPIO module
- `ctx.gpio_sem`: an asyncio.Semaphore to serialize GPIO access
- `ctx.role_pin_assignments`: a dict mapping `(sensor_name, role)` to assigned BCM pin, for multi-pin plugins
"""

from __future__ import annotations

from typing import Optional, Tuple, Protocol, runtime_checkable


Result = Tuple[str, str, str]


@runtime_checkable
class GPIOSensorPlugin(Protocol):
    name: str
    auto_detectable: bool
    bus_type: str
    pin_roles: list[str]

    async def detect(self, pin: int, ctx) -> Optional[Result]:
        ...

    async def read(self, pin: int, ctx) -> Optional[Result]:
        ...

    async def details(self, phys_pin: int, bcm_pin: int | None, ctx) -> str:
        ...

    # Optional multi-pin helpers
    async def detect_with_roles(self, roles: dict[str, int], ctx) -> Optional[Result]:
        ...

    async def read_with_roles(self, roles: dict[str, int], ctx) -> Optional[Result]:
        ...
