"""
MAVLink core abstraction to decouple the FastAPI backend from a specific
implementation (PyMAVLink vs. a future MAVLink.dll binding).

Default implementation uses PyMAVLink. A placeholder DLL adapter is provided
for future integration without changing the rest of the codebase.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional


class BaseMavlinkCore:
    """Abstract interface for MAVLink operations used by the server."""

    target_system: int
    target_component: int

    def connect(self, connection_string: str, baud: int) -> None:
        raise NotImplementedError

    def wait_heartbeat(self, timeout: Optional[float] = None) -> None:
        raise NotImplementedError

    def recv_match(self, type: Optional[Iterable[str] | str] = None, *, blocking: bool = False, timeout: Optional[float] = None):
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    @property
    def mav(self) -> Any:
        """Return an object exposing MAVLink send helpers (e.g., command_long_send)."""
        raise NotImplementedError


class PyMavlinkCore(BaseMavlinkCore):
    """PyMAVLink-backed implementation that mirrors the existing API shape."""

    def __init__(self) -> None:
        # Lazy import to keep dependency localized
        from pymavlink import mavutil  # type: ignore

        self._mavutil = mavutil
        self._master = None
        self.target_system = 0
        self.target_component = 0

    def connect(self, connection_string: str, baud: int) -> None:
        self._master = self._mavutil.mavlink_connection(connection_string, baud=baud)
        # target_system/component are populated after first heartbeat, but keep current values in sync when available
        self.target_system = getattr(self._master, "target_system", 1)
        self.target_component = getattr(self._master, "target_component", 1)

    def wait_heartbeat(self, timeout: Optional[float] = None) -> None:
        if self._master is None:
            raise RuntimeError("PyMavlinkCore not connected")
        self._master.wait_heartbeat(timeout=timeout)
        # Refresh targets after handshake
        self.target_system = getattr(self._master, "target_system", 1)
        self.target_component = getattr(self._master, "target_component", 1)

    def recv_match(self, type: Optional[Iterable[str] | str] = None, *, blocking: bool = False, timeout: Optional[float] = None):
        if self._master is None:
            return None
        return self._master.recv_match(type=type, blocking=blocking, timeout=timeout)

    def close(self) -> None:
        if self._master is not None:
            try:
                self._master.close()
            finally:
                self._master = None

    @property
    def mav(self) -> Any:
        if self._master is None:
            raise RuntimeError("PyMavlinkCore not connected")
        return self._master.mav


class DllMavlinkCore(BaseMavlinkCore):
    """
    Placeholder adapter for a future MAVLink.dll binding.

    Implementations should load the DLL (ctypes/cffi), perform initialization,
    and expose an object compatible with the `.mav` attribute used by server.py,
    as well as provide `recv_match` that yields objects with `.get_type()` and
    attribute access for fields (lat, lon, etc.).
    """

    def __init__(self) -> None:
        self._dll = None
        self._mav_proxy = None
        self.target_system = 1
        self.target_component = 1

    def connect(self, connection_string: str, baud: int) -> None:
        raise NotImplementedError(
            "DllMavlinkCore is a stub. Provide bindings to MAVLink.dll and implement connect()."
        )

    def wait_heartbeat(self, timeout: Optional[float] = None) -> None:
        raise NotImplementedError("DllMavlinkCore.wait_heartbeat() not implemented")

    def recv_match(self, type: Optional[Iterable[str] | str] = None, *, blocking: bool = False, timeout: Optional[float] = None):
        raise NotImplementedError("DllMavlinkCore.recv_match() not implemented")

    def close(self) -> None:
        # Optional: implement if the DLL exposes a close/shutdown
        pass

    @property
    def mav(self) -> Any:
        if self._mav_proxy is None:
            raise RuntimeError("DllMavlinkCore not connected")
        return self._mav_proxy


def get_mavlink_core() -> BaseMavlinkCore:
    """Factory that selects implementation based on env var MAVLINK_BACKEND."""
    backend = os.getenv("MAVLINK_BACKEND", "pymavlink").lower()
    if backend in ("dll", "mavlink.dll", "mavlink_dll"):
        return DllMavlinkCore()
    return PyMavlinkCore()

