"""Background hardware sampling; sensor failures never stop the application."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Callable

from .hardware import HardwareCollector
from .run_log import RunLog


class HardwareMonitor:
    """Keep sensor calls off the launcher and Godot main threads.

    A driver call cannot safely be interrupted in Python. The daemon worker owns
    collector cleanup; stop bounds the wait and suppresses late publications.
    """

    def __init__(
        self,
        run_log: RunLog,
        root_pid: int,
        data_path: Path,
        *,
        interval_seconds: float = 1.0,
        collector_factory: Callable | None = None,
    ) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Hardware interval must be finite and positive")
        self.log = run_log
        self.root_pid = root_pid
        self.data_path = data_path
        self.interval = interval_seconds
        self.factory = collector_factory or HardwareCollector
        self._stop = threading.Event()
        self._registration_lock = threading.Lock()
        self._pending: dict[int, str] = {}
        self._thread: threading.Thread | None = None
        self._failed = False

    def start(self) -> None:
        if self._thread is not None or self._stop.is_set():
            return
        self._thread = threading.Thread(
            target=self._run, name="civic-hardware-monitor", daemon=True
        )
        try:
            self._thread.start()
        except RuntimeError as error:
            self._failed = True
            self.log.hardware_status("unavailable", str(error))

    def register_process(self, pid: int | None, role: str) -> None:
        if type(pid) is not int or pid <= 0 or self._stop.is_set():
            return
        with self._registration_lock:
            if len(self._pending) < 64:
                self._pending[pid] = role

    def _run(self) -> None:
        collector = None
        try:
            inventory_started = time.perf_counter()
            collector = self.factory(self.root_pid, self.data_path)
            inventory = collector.inventory()
            inventory["collection_ms"] = round(
                (time.perf_counter() - inventory_started) * 1000, 3
            )
            if self._stop.is_set():
                return
            self.log.hardware_inventory(inventory)
            failures = 0
            while not self._stop.is_set():
                started = time.monotonic()
                collection_started = time.perf_counter()
                try:
                    with self._registration_lock:
                        registrations = self._pending
                        self._pending = {}
                    for pid, role in registrations.items():
                        collector.register_process(pid, role)
                    sample = collector.sample()
                    sample["collection_ms"] = round(
                        (time.perf_counter() - collection_started) * 1000, 3
                    )
                    if self._stop.is_set():
                        break
                    self.log.hardware_sample(sample)
                    failures = 0
                except Exception as error:
                    if self._stop.is_set():
                        break
                    failures += 1
                    self.log.hardware_warning(f"{type(error).__name__}: {error}")
                    if failures >= 3:
                        raise RuntimeError(
                            "Three consecutive hardware samples failed"
                        ) from error
                # No catch-up bursts if a sensor is slower than the interval.
                self._stop.wait(max(0.05, self.interval - (time.monotonic() - started)))
        except Exception as error:
            self._failed = True
            if not self._stop.is_set():
                self.log.hardware_status(
                    "unavailable", f"{type(error).__name__}: {error}"
                )
        finally:
            if collector is not None:
                try:
                    collector.close()
                except Exception as error:
                    if not self._stop.is_set():
                        self.log.hardware_warning(f"Sensor cleanup: {error}")

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.ident is not None:
            thread.join(max(0.0, timeout))
        if thread is not None and thread.is_alive():
            self.log.hardware_status(
                "timed_out",
                "Sensor call did not finish before shutdown; late results ignored",
            )
        elif not self._failed:
            self.log.hardware_status("stopped")
