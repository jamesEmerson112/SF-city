"""Windows cleanup for process trees owned by the application launcher."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import time


def terminate_windows_tree(process: subprocess.Popen) -> None:
    """Close descendants even when taskkill/WMI is unavailable.

    Hold process handles before terminating anything. Creation times exclude
    stale parent IDs and any PID reused after the process snapshot was taken.
    Only descendants of the still-live Popen handle can enter the tree.
    """
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("exe", wintypes.WCHAR * 260),
        ]

    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD

    def created(handle: int) -> int:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(
            handle, *(ctypes.byref(value) for value in times)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    if process.poll() is not None:
        return
    root_handle = int(process._handle)
    root_created = created(root_handle)
    # FILETIME counts 100 ns intervals since 1601-01-01 UTC.
    snapshot_started = time.time_ns() // 100 + 116444736000000000
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents: dict[int, int] = {}
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        while True:
            parents[entry.pid] = entry.parent
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel.CloseHandle(snapshot)

    owned = {process.pid: (root_handle, root_created)}
    handles: list[int] = []
    try:
        frontier = [process.pid]
        while frontier:
            next_frontier = []
            for pid, parent in parents.items():
                if parent not in frontier or pid in owned:
                    continue
                handle = kernel.OpenProcess(0x1000 | 0x100000 | 0x1, False, pid)
                if not handle:
                    if ctypes.get_last_error() == 87:  # Already exited.
                        continue
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)
                creation = created(handle)
                if owned[parent][1] <= creation <= snapshot_started:
                    owned[pid] = (handle, creation)
                    next_frontier.append(pid)
            frontier = next_frontier
        # Descendants first; venv launcher parents often exit as a consequence.
        for handle, _ in reversed(list(owned.values())):
            if kernel.WaitForSingleObject(handle, 0) == 0:
                continue
            if not kernel.TerminateProcess(handle, 1):
                if kernel.WaitForSingleObject(handle, 0) != 0:
                    raise ctypes.WinError(ctypes.get_last_error())
        for handle, _ in owned.values():
            if kernel.WaitForSingleObject(handle, 3000) != 0:
                raise RuntimeError("An owned application process did not terminate")
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
