from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass
from typing import Any


class MpvIpcError(RuntimeError):
    pass


def _is_windows_pipe(endpoint: str) -> bool:
    return os.name == "nt" and endpoint.startswith("\\\\.\\pipe\\")


def _open_windows_named_pipe(endpoint: str):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    CreateFileW.restype = wintypes.HANDLE

    handle = CreateFileW(
        endpoint,
        GENERIC_READ | GENERIC_WRITE,
        0,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise OSError(err, f"CreateFileW failed for named pipe {endpoint}")

    fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    return os.fdopen(fd, "r+b")


@dataclass
class MpvIpcClient:
    endpoint: str
    connect_timeout_sec: float = 2.0

    def _open(self):
        deadline = time.time() + self.connect_timeout_sec
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                if _is_windows_pipe(self.endpoint):
                    return _open_windows_named_pipe(self.endpoint)
                return open(self.endpoint, "r+b")
            except OSError as exc:
                last_err = exc
                time.sleep(0.1)
        raise MpvIpcError(f"Unable to connect to mpv IPC at {self.endpoint}: {last_err}")

    def command(self, cmd: list[Any], timeout_sec: float = 2.0) -> dict[str, Any]:
        request_id = int(time.time() * 1000) % 1_000_000_000
        payload = {"command": cmd, "request_id": request_id}
        with self._open() as pipe:
            pipe.write((json.dumps(payload) + "\n").encode("utf-8"))
            pipe.flush()

            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                line = pipe.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                try:
                    msg = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if msg.get("request_id") == request_id:
                    return msg
            raise MpvIpcError(f"Timed out waiting for mpv IPC reply for command: {cmd!r}")

    def get_property(self, name: str) -> Any:
        resp = self.command(["get_property", name])
        if resp.get("error") != "success":
            raise MpvIpcError(f"mpv get_property {name!r} failed: {resp}")
        return resp.get("data")

    def show_text(self, text: str, duration_ms: int = 1200) -> None:
        self.command(["show-text", text, int(duration_ms)])
