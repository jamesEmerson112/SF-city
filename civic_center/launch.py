"""Own the local simulation worker and the Godot viewer lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .hardware_monitor import HardwareMonitor
from .run_log import RunLog
from .scenario import POPULATIONS, load_scenario, scenario_hash
from .telemetry import TelemetryHub

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "viewer"


def _prepared_city_scenario(
    geography: Path,
    terrain: Path | None,
    population: int,
    seed: int,
    landuse: Path | None = None,
) -> Path:
    """Reuse a deterministic scenario only when source data and builder agree."""
    from .city_scenario import CITY_POPULATIONS, build_city_scenario
    from .geography import atomic_write

    if population not in CITY_POPULATIONS:
        raise ValueError(
            f"Citywide cohort presets are {CITY_POPULATIONS}; use --world pilot for the 5000-person stress scene"
        )
    digest = hashlib.sha256()
    for source in [
        geography,
        *([terrain] if terrain else []),
        *([landuse] if landuse else []),
        *[
            ROOT / "civic_center" / name
            for name in (
                "city_scenario.py",
                "scenario.py",
                "geography.py",
                "terrain.py",
                "landuse.py",
            )
        ],
    ]:
        payload = source.read_bytes()
        digest.update(len(payload).to_bytes(8, "little"))
        digest.update(payload)
    digest.update(json.dumps({"population": population, "seed": seed}).encode())
    target = ROOT / ".local/civic/scenarios" / f"sf-{digest.hexdigest()[:24]}.json"
    if target.is_file():
        cached = load_scenario(target)
        if _relocate_cached_sources(cached, geography, terrain, landuse):
            atomic_write(
                target,
                json.dumps(cached, separators=(",", ":"), allow_nan=False).encode(
                    "utf-8"
                ),
            )
        return target
    print(
        f"Preparing {population} residents on the San Francisco street network...",
        flush=True,
    )
    options = {"population": population, "seed": seed, "terrain_path": terrain}
    if landuse is not None:
        options["landuse_path"] = landuse
    scenario = build_city_scenario(geography, **options)
    atomic_write(
        target,
        json.dumps(scenario, separators=(",", ":"), allow_nan=False).encode("utf-8"),
    )
    return target


def _relocate_cached_sources(
    scenario: dict, geography: Path, terrain: Path | None, landuse: Path | None = None
) -> bool:
    """A portable folder can move without preserving its former absolute paths.

    Only used after the cache key has matched the actual source bytes and code.
    Explicit scenario files and saved checkpoints are never silently rewritten.
    """
    changed = False
    for key, source in (
        ("geography_manifest", geography),
        ("terrain_manifest", terrain),
        ("landuse_manifest", landuse),
    ):
        if source is not None and scenario.get(key) != str(source.resolve()):
            scenario[key] = str(source.resolve())
            changed = True
    if terrain is not None and isinstance(scenario.get("terrain"), dict):
        value = str(terrain.resolve())
        if scenario["terrain"].get("path") != value:
            scenario["terrain"]["path"] = value
            changed = True
    if changed:
        scenario["sha256"] = scenario_hash(scenario)
    return changed


def find_godot() -> str:
    configured = os.environ.get("GODOT_BIN")
    bundled = ROOT / "runtime/godot"
    candidates = (
        ([configured] if configured else [])
        + [str(path) for path in sorted(bundled.glob("Godot*console.exe"))]
        + [
            shutil.which("godot"),
            shutil.which("godot4"),
        ]
    )
    candidates += [
        str(path)
        for path in sorted((ROOT / "comparison/.tools/godot").glob("Godot*console.exe"))
    ]
    for candidate in candidates:
        if candidate and (Path(candidate).is_file() or shutil.which(candidate)):
            return candidate
    raise RuntimeError(
        "Godot 4 was not found. Set GODOT_BIN or install the portable engine described in viewer/README.md."
    )


class _LaunchCancelled(RuntimeError):
    """The user closed the owned viewer during startup."""


def _read_ready(
    process: subprocess.Popen,
    timeout: float,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    result: queue.Queue = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            line = process.stdout.readline()
            result.put(
                json.loads(line)
                if line
                else RuntimeError("Simulation worker exited before readiness")
            )
        except Exception as error:
            result.put(error)

    threading.Thread(target=read, name="civic-worker-readiness", daemon=True).start()
    deadline = time.monotonic() + timeout
    while True:
        if cancelled is not None and cancelled():
            raise _LaunchCancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Simulation worker did not become ready in time")
        try:
            ready = result.get(timeout=min(remaining, 0.1))
            break
        except queue.Empty:
            continue
    if isinstance(ready, Exception):
        raise RuntimeError(f"Simulation worker startup failed: {ready}") from ready
    if (
        not isinstance(ready, dict)
        or ready.get("type") != "ready"
        or type(ready.get("port")) is not int
        or not 1 <= ready["port"] <= 65535
    ):
        raise RuntimeError("Simulation worker returned invalid readiness information")
    return ready


def _prepare_with_viewer(
    viewer: subprocess.Popen,
    status_path: Path,
    geography: Path,
    terrain: Path | None,
    population: int,
    seed: int,
    landuse: Path | None,
    timeout: float,
    hardware_monitor: HardwareMonitor | None = None,
    run_log: RunLog | None = None,
) -> Path:
    """Keep the loading window closable during first-time city generation."""
    from .startup import write_status

    request = status_path.with_suffix(".request.json")
    result = status_path.with_suffix(".result.json")
    output = status_path.with_suffix(".prepare.log")
    write_status(
        request,
        "preparing",
        "Preparing residents",
        geography=str(geography.resolve()),
        terrain=str(terrain.resolve()) if terrain else None,
        population=population,
        seed=seed,
        landuse=str(landuse.resolve()) if landuse else None,
    )
    child = None
    try:
        with output.open("w", encoding="utf-8") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "civic_center.startup",
                    "--request",
                    str(request),
                    "--result",
                    str(result),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE if run_log is not None else log,
                stderr=subprocess.STDOUT if run_log is not None else log,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            preparation_reader = None
            if run_log is not None and getattr(child, "stdout", None) is not None:
                preparation_reader = run_log.capture(
                    child.stdout, source="preparation", archive=log, echo=False
                )
            if hardware_monitor is not None:
                hardware_monitor.register_process(
                    getattr(child, "pid", None), "preparation"
                )
            try:
                deadline = time.monotonic() + timeout
                while child.poll() is None:
                    if viewer.poll() is not None:
                        raise _LaunchCancelled()
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "City preparation did not finish before its timeout"
                        )
                    time.sleep(0.1)
            finally:
                if child.poll() is None:
                    outcome = (
                        _cleanup_stage(
                            run_log, "preparation", lambda: _terminate_tree(child)
                        )
                        if run_log is not None
                        else _terminate_tree(child)
                    )
                    if outcome["status"] == "failed":
                        raise RuntimeError("Owned city preparation did not terminate")
                if preparation_reader is not None:
                    preparation_reader.join(2.0)
        if viewer.poll() is not None:
            raise _LaunchCancelled()
        if not result.is_file():
            raise RuntimeError(f"City preparation failed; see {output}")
        record = json.loads(result.read_text(encoding="utf-8"))
        if child.returncode != 0 or record.get("status") != "ready":
            raise RuntimeError(record.get("message", "City preparation failed"))
        scenario = Path(record["scenario"])
        if not scenario.is_file():
            raise RuntimeError("City preparation did not produce a scenario")
        return scenario
    finally:
        if child is not None and child.poll() is None:
            outcome = (
                _cleanup_stage(run_log, "preparation", lambda: _terminate_tree(child))
                if run_log is not None
                else _terminate_tree(child)
            )
            if outcome["status"] == "failed" and run_log is None:
                raise RuntimeError("Owned city preparation did not terminate")
        for name, path in (
            ("preparation_request", request),
            ("preparation_result", result),
        ):
            if run_log is not None:
                _cleanup_stage(
                    run_log, name, lambda target=path: target.unlink(missing_ok=True)
                )
            else:
                path.unlink(missing_ok=True)


def _process_outcome(
    process: subprocess.Popen, started: float, status: str, **fields
) -> dict:
    return {
        "status": status,
        "exit_code": process.poll(),
        "forced": status == "forced",
        "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        **fields,
    }


def _shutdown_worker(process: subprocess.Popen, port: int | None, token: str) -> dict:
    """Ask the owned worker to exit, then report whether termination was required.

    Read small acknowledgment frames without retaining the potentially large scene
    preceding them. The grace deadline includes socket draining and process joining.
    """
    started = time.monotonic()
    if process.poll() is not None:
        return _process_outcome(process, started, "already_exited", acknowledged=False)
    acknowledged = False
    reason = "worker_endpoint_unavailable"
    if port:
        try:
            deadline = started + 8.0
            with socket.create_connection(("127.0.0.1", port), timeout=1) as connection:
                hello = {
                    "type": "hello",
                    "protocol_version": 1,
                    "token": token,
                    "snapshot_encoding": "city-routes-v1",
                    "command_status": True,
                }
                shutdown = {
                    "type": "command",
                    "request_id": "launcher-shutdown",
                    "action": "shutdown",
                }
                connection.sendall(
                    (json.dumps(hello) + "\n" + json.dumps(shutdown) + "\n").encode()
                )
                pending = bytearray()
                oversized = False
                while time.monotonic() < deadline:
                    connection.settimeout(
                        min(0.5, max(0.001, deadline - time.monotonic()))
                    )
                    try:
                        chunk = connection.recv(65536)
                    except socket.timeout:
                        if process.poll() is not None:
                            break
                        continue
                    if not chunk:
                        break
                    pieces = chunk.split(b"\n")
                    for index, piece in enumerate(pieces):
                        if not oversized:
                            if len(pending) + len(piece) > 8192:
                                oversized = True
                                pending.clear()
                            else:
                                pending.extend(piece)
                        if index == len(pieces) - 1:
                            continue
                        if not oversized:
                            try:
                                message = json.loads(pending)
                            except (ValueError, UnicodeError, RecursionError):
                                message = None
                            if isinstance(message, dict) and (
                                message.get("type") == "ack"
                                and message.get("action") == "shutdown"
                                and message.get("request_id") == "launcher-shutdown"
                            ):
                                acknowledged = True
                        pending.clear()
                        oversized = False
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
            status = "graceful" if acknowledged else "already_exited"
            if process.returncode != 0:
                status = "failed"
            return _process_outcome(
                process,
                started,
                status,
                acknowledged=acknowledged,
                reason=(
                    None if acknowledged else "exited_without_shutdown_acknowledgment"
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            reason = (
                "worker_shutdown_timeout"
                if isinstance(error, subprocess.TimeoutExpired)
                else "worker_connection_failed"
            )
    outcome = _terminate_tree(process)
    outcome.update(
        acknowledged=acknowledged,
        reason=outcome.get("reason") or reason,
        elapsed_ms=round((time.monotonic() - started) * 1000, 3),
    )
    return outcome


def _terminate_tree(process: subprocess.Popen) -> dict:
    """Terminate only a process tree started by this launcher.

    Windows venv python.exe can be a parent launcher for the real interpreter;
    killing only that parent would leave a worker behind after startup failure.
    """
    started = time.monotonic()
    if process.poll() is not None:
        return _process_outcome(process, started, "already_exited")
    try:
        if sys.platform == "win32":
            from .processes import terminate_windows_tree

            terminate_windows_tree(process)
            process.wait(timeout=3)
        else:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return _process_outcome(
            process,
            started,
            "failed",
            forced=True,
            reason=f"{type(error).__name__}: {error}",
        )
    return _process_outcome(process, started, "forced")


def _cleanup_stage(log: RunLog, name: str, operation: Callable) -> dict:
    """One cleanup failure must not suppress another stage or the final archive."""
    started = time.monotonic()
    try:
        result = operation()
        outcome = dict(result) if isinstance(result, dict) else {"status": "completed"}
    except Exception as error:
        outcome = {"status": "failed", "reason": f"{type(error).__name__}: {error}"}
    outcome.setdefault("elapsed_ms", round((time.monotonic() - started) * 1000, 3))
    log.cleanup_stage(name, outcome)
    if outcome.get("status") == "failed":
        log.error(
            f"{name}: {outcome.get('reason', 'cleanup failed')}", source="cleanup"
        )
    return outcome


def _stop_monitor(monitor) -> dict:
    monitor.stop()
    thread = getattr(monitor, "_thread", None)
    alive = thread is not None and thread.is_alive()
    return {"status": "timed_out" if alive else "stopped", "timed_out": alive}


def _start_viewer(
    command: list[str], environment: dict[str, str], run_log: RunLog
) -> subprocess.Popen:
    """Drain Godot output continuously while retaining structured diagnostics."""
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    run_log.event("viewer_started", pid=getattr(process, "pid", None))
    stream = getattr(process, "stdout", None)
    if stream is not None:
        run_log.capture(stream)
    return process


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=int, choices=POPULATIONS, default=200)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--world",
        choices=("auto", "city", "pilot"),
        default="auto",
        help="Use the real city when geography is installed, or choose the stylized pilot",
    )
    parser.add_argument("--scenario", type=Path)
    parser.add_argument(
        "--load", type=Path, help="Resume a validated saved resident day"
    )
    parser.add_argument(
        "--geography",
        type=Path,
        help="Citywide geography manifest; detected from .local/civic/geography when present",
    )
    parser.add_argument(
        "--no-geography",
        action="store_true",
        help="Load only the detailed City Hall pilot",
    )
    parser.add_argument(
        "--terrain",
        type=Path,
        help="Terrain grid; detected from .local/civic/terrain when present",
    )
    parser.add_argument(
        "--landuse",
        type=Path,
        help="Official parcel uses; detected from .local/civic/landuse when present",
    )
    parser.add_argument(
        "--no-landuse",
        action="store_true",
        help="Generate the earlier synthetic-use cohort without the optional parcel-use source",
    )
    parser.add_argument(
        "--location", choices=("city", "city-hall"), default="city-hall"
    )
    parser.add_argument(
        "--place", help="Start at a named neighborhood or Recreation and Parks property"
    )
    parser.add_argument(
        "--lighting",
        choices=("cycle", "fixed"),
        default="cycle",
        help="Follow a representative September daylight cycle or keep fixed inspection light",
    )
    parser.add_argument(
        "--facades",
        choices=("on", "off"),
        default="on",
        help="Show or hide illustrative window patterns on nearby buildings",
    )
    parser.add_argument(
        "--trees",
        choices=("on", "off"),
        default="on",
        help="Show or hide the optional street-tree layer at recorded source locations",
    )
    parser.add_argument(
        "--mode",
        choices=("overhead", "walk", "follow", "map"),
        default="overhead",
        help="Start in a 3D camera view or the lightweight 2D agent map",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--window-size", help="Initial viewer size, for example 1920x1080"
    )
    parser.add_argument(
        "--window-mode", choices=("windowed", "maximized", "fullscreen")
    )
    parser.add_argument("--ui-scale", type=float, choices=(1.0, 1.25, 1.5))
    parser.add_argument(
        "--performance", action="store_true", help="Open live diagnostics"
    )
    parser.add_argument(
        "--no-display-settings",
        action="store_true",
        help="Ignore saved display preferences for reproducible runs",
    )
    parser.add_argument("--workspace-probe", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--menu-probe", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--menu-probe-case",
        default="save_exit",
        choices=("save_exit", "window_close", "save_error", "population_exit"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        help="Named checkpoint directory; defaults to .local/civic/saves",
    )
    parser.add_argument(
        "--probe-counts", default="200,500,1000,2000,5000", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--probe-seconds", type=float, default=3.0, help=argparse.SUPPRESS
    )
    parser.add_argument("--probe-layouts", action="store_true", help=argparse.SUPPRESS)

    parser.add_argument(
        "--render-cache",
        type=Path,
        help="Prepared static scenery directory; defaults to .local/civic/render-cache",
    )
    parser.add_argument(
        "--no-render-cache",
        action="store_true",
        help="Build static scenery without reading or writing prepared geometry",
    )
    parser.add_argument(
        "--use-overlay",
        action="store_true",
        help="Start with the observed parcel-use colors enabled",
    )
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--replay-index", type=int, default=0)
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=None,
        help="Worker startup deadline; defaults to 120 seconds for saved/city days, 20 for the pilot",
    )
    parser.add_argument("--smoke-timeout", type=float, default=90)
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Per-run JSON diagnostics directory; defaults to .local/civic/logs",
    )
    parser.add_argument(
        "--no-hardware-monitor",
        action="store_true",
        help="Disable background hardware sampling for this run",
    )
    parser.add_argument(
        "--hardware-interval",
        type=float,
        default=1.0,
        help="Hardware sampling interval in seconds (0.25 to 60; default 1)",
    )
    args = parser.parse_args(argv)
    if args.window_size:
        parts = args.window_size.lower().split("x")
        if (
            len(parts) != 2
            or not all(part.isdecimal() for part in parts)
            or not 320 <= int(parts[0]) <= 16384
            or not 240 <= int(parts[1]) <= 16384
        ):
            parser.error(
                "Window size must be WIDTHxHEIGHT within 320x240 and 16384x16384"
            )
        args.window_size = "x".join(str(int(part)) for part in parts)
    if not math.isfinite(args.probe_seconds) or args.probe_seconds <= 0:
        parser.error("Probe duration must be finite and positive")
    if args.workspace_probe and args.menu_probe:
        parser.error("Choose either --workspace-probe or --menu-probe")
    if args.workspace_probe:
        try:
            counts = [int(part) for part in args.probe_counts.split(",")]
        except ValueError:
            parser.error("Probe counts must be comma-separated integers")
        if (
            not counts
            or len(counts) > 64
            or any(not 1 <= count <= 5000 for count in counts)
        ):
            parser.error(
                "Probe counts must contain 1 to 64 populations between 1 and 5000"
            )

    if (
        not math.isfinite(args.hardware_interval)
        or not 0.25 <= args.hardware_interval <= 60
    ):
        parser.error("Hardware interval must be finite and between 0.25 and 60 seconds")
    if args.headless and args.screenshot:
        parser.error("A screenshot requires a rendered window; omit --headless")
    if args.scenario and args.load:
        parser.error("Choose either --scenario or --load")
    if args.replay and args.load:
        parser.error("Choose either --replay or --load")
    if args.geography and args.no_geography:
        parser.error("Choose either --geography or --no-geography")
    if args.landuse and args.no_landuse:
        parser.error("Choose either --landuse or --no-landuse")
    if (
        args.startup_timeout is not None and args.startup_timeout <= 0
    ) or args.smoke_timeout <= 0:
        parser.error("Timeouts must be positive")

    worker = None
    viewer = None
    worker_log = None
    port = None
    token = secrets.token_urlsafe(24)
    telemetry_token = secrets.token_urlsafe(24)
    telemetry = None
    log_path = None
    startup_path = None
    run_status = "failed"
    exit_code = 1
    hardware_monitor = None
    early_worker_cleanup = None
    run_log = RunLog(
        args.log_dir or ROOT / ".local/civic/logs",
        vars(args),
        secrets=(token, telemetry_token),
    )
    if not run_log.disabled:
        print(f"Run log: {run_log.path}", flush=True)
    run_log.configure_hardware(
        enabled=not args.no_hardware_monitor, interval_seconds=args.hardware_interval
    )
    try:
        try:
            telemetry = TelemetryHub(run_log.run_id, telemetry_token)
            telemetry.start()
            run_log.attach_telemetry(telemetry)
        except (OSError, RuntimeError) as error:
            telemetry = None
            run_log.event("telemetry_unavailable", message=str(error))
        if not args.no_hardware_monitor:
            hardware_monitor = HardwareMonitor(
                run_log, os.getpid(), ROOT, interval_seconds=args.hardware_interval
            )
            hardware_monitor.start()
        godot = find_godot()
        run_log.update(
            runtime={
                "godot": godot,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
                "launcher_pid": os.getpid(),
            }
        )
        if not (VIEWER / "project.godot").is_file():
            raise RuntimeError("The Godot application is missing viewer/project.godot")
        if not (VIEWER / "assets/civic-center.glb").is_file():
            raise RuntimeError(
                "The packaged City Hall model is missing. Run scripts/stage_civic_assets.py."
            )
        runtime = [godot, "--path", str(VIEWER)]
        if args.headless:
            runtime.append("--headless")
        viewer_options = [
            "--launcher-owned",
            "--mode",
            args.mode,
            "--location",
            args.location,
        ]
        if telemetry is not None:
            viewer_options += [
                "--telemetry-port",
                str(telemetry.port),
                "--telemetry-token",
                telemetry_token,
            ]
        for name in ("window_size", "window_mode", "ui_scale"):
            value = getattr(args, name)
            if value is not None:
                viewer_options += ["--" + name.replace("_", "-"), str(value)]
        for name in ("performance", "no_display_settings", "probe_layouts"):
            if getattr(args, name):
                viewer_options.append("--" + name.replace("_", "-"))
        if args.workspace_probe:
            args.workspace_probe.parent.mkdir(parents=True, exist_ok=True)
            viewer_options += [
                "--workspace-probe",
                str(args.workspace_probe.resolve()),
                "--probe-counts",
                args.probe_counts,
                "--probe-seconds",
                str(args.probe_seconds),
            ]
        if args.menu_probe:
            args.menu_probe.parent.mkdir(parents=True, exist_ok=True)
            viewer_options += [
                "--menu-probe",
                str(args.menu_probe.resolve()),
                "--menu-probe-case",
                args.menu_probe_case,
            ]
        viewer_options += ["--lighting", args.lighting]
        viewer_options += ["--facades", args.facades]
        viewer_options += ["--trees", args.trees]
        if args.place:
            viewer_options += ["--place", args.place]
        if args.use_overlay:
            viewer_options.append("--use-overlay")
        user_data = ROOT / ".local/civic"
        user_data.mkdir(parents=True, exist_ok=True)
        render_cache = args.render_cache or user_data / "render-cache"
        viewer_options += ["--render-cache", str(render_cache.resolve())]
        if args.no_render_cache:
            viewer_options.append("--no-render-cache")
        if args.smoke_test:
            viewer_options.append("--smoke-test")
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            viewer_options += ["--screenshot", str(args.screenshot.resolve())]
        runtime_environment = os.environ.copy()
        if sys.platform == "win32":
            for key, leaf in [("APPDATA", "roaming"), ("LOCALAPPDATA", "local")]:
                path = user_data / "runtime" / leaf
                path.mkdir(parents=True, exist_ok=True)
                runtime_environment[key] = str(path)
        if not args.replay:
            from .startup import write_status

            startup_path = (
                ROOT / ".cache" / f"startup-{os.getpid()}-{time.time_ns()}.json"
            )
            write_status(startup_path, "preparing", "Preparing your city")
            viewer = _start_viewer(
                runtime
                + ["--"]
                + viewer_options
                + ["--startup-file", str(startup_path)],
                runtime_environment,
                run_log,
            )
            if hardware_monitor is not None:
                hardware_monitor.register_process(
                    getattr(viewer, "pid", None), "viewer"
                )
            run_log.update(status="loading")
        geography = args.geography or user_data / "geography/sf-geography.json"
        terrain = args.terrain or user_data / "terrain/terrain.json"
        landuse = args.landuse or user_data / "landuse/landuse.json"
        scenario_path = args.scenario
        if scenario_path:
            scenario_metadata = load_scenario(scenario_path)
            if not args.geography and scenario_metadata.get("geography_manifest"):
                geography = Path(scenario_metadata["geography_manifest"])
            if not args.terrain and scenario_metadata.get("terrain_manifest"):
                terrain = Path(scenario_metadata["terrain_manifest"])
        if args.geography and not geography.is_file():
            raise RuntimeError(f"Geography manifest not found: {geography}")
        if args.terrain and not terrain.is_file():
            raise RuntimeError(f"Terrain grid not found: {terrain}")
        if args.landuse and not landuse.is_file():
            raise RuntimeError(f"Land-use data not found: {landuse}")
        if not (args.scenario or args.load or args.replay) and args.world != "pilot":
            if geography.is_file():
                write_status(
                    startup_path,
                    "preparing",
                    "Preparing homes, jobs and daily commutes",
                )
                preparation_started = time.monotonic()
                run_log.event("scenario_preparation_started")
                scenario_path = _prepare_with_viewer(
                    viewer,
                    startup_path,
                    geography,
                    terrain if terrain.is_file() else None,
                    args.population,
                    args.seed,
                    landuse if not args.no_landuse and landuse.is_file() else None,
                    args.startup_timeout or 600,
                    hardware_monitor=hardware_monitor,
                    run_log=run_log,
                )
                run_log.event(
                    "scenario_preparation_completed",
                    duration_seconds=time.monotonic() - preparation_started,
                    scenario=scenario_path.resolve(),
                )
            elif args.world == "city":
                raise RuntimeError(
                    "City geography is not installed. Run venv\\Scripts\\python.exe scripts/fetch_sf_geography.py first."
                )
        if not args.no_geography and geography.is_file():
            viewer_options += ["--geography", str(geography.resolve())]
            if terrain.is_file():
                viewer_options += ["--terrain", str(terrain.resolve())]
        run_log.update(
            inputs={
                "scenario": scenario_path.resolve() if scenario_path else None,
                "load": args.load.resolve() if args.load else None,
                "replay": args.replay.resolve() if args.replay else None,
                "geography": (
                    geography.resolve()
                    if not args.no_geography and geography.is_file()
                    else None
                ),
                "terrain": (
                    terrain.resolve()
                    if not args.no_geography
                    and geography.is_file()
                    and terrain.is_file()
                    else None
                ),
                "landuse": (
                    landuse.resolve()
                    if scenario_path
                    and not (args.scenario or args.load or args.replay)
                    and not args.no_landuse
                    and landuse.is_file()
                    else (
                        scenario_metadata.get("landuse_manifest")
                        if args.scenario
                        else None
                    )
                ),
                "render_cache": render_cache.resolve(),
                "render_cache_enabled": not args.no_render_cache,
            }
        )
        if args.replay:
            if not args.replay.is_file():
                raise RuntimeError(f"Replay file not found: {args.replay}")
            viewer_options += [
                "--replay",
                str(args.replay.resolve()),
                "--replay-index",
                str(args.replay_index),
            ]
        else:
            cache = ROOT / ".cache"
            cache.mkdir(exist_ok=True)
            log_path = cache / f"civic-worker-{os.getpid()}-{time.time_ns()}.log"
            worker_log = log_path.open("w", encoding="utf-8")
            run_log.update(worker_log=log_path.resolve())
            command = [
                sys.executable,
                "-u",
                "-m",
                "civic_center.worker",
                "--port",
                "0",
                f"--token={token}",
                "--population",
                str(args.population),
                "--seed",
                str(args.seed),
                "--save-dir",
                str((args.save_dir or user_data / "saves").resolve()),
            ]
            if scenario_path:
                command += ["--scenario", str(scenario_path.resolve())]
            if args.load:
                command += ["--load", str(args.load.resolve())]
            if viewer.poll() is not None:
                raise _LaunchCancelled()
            write_status(
                startup_path,
                "preparing",
                (
                    "Restoring your saved day"
                    if args.load
                    else "Preparing resident routes"
                ),
            )
            worker_started = time.monotonic()
            worker = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if hardware_monitor is not None:
                hardware_monitor.register_process(
                    getattr(worker, "pid", None), "worker"
                )
            if getattr(worker, "stderr", None) is not None:
                run_log.capture(
                    worker.stderr, source="worker", archive=worker_log, echo=False
                )
            run_log.event("worker_started", pid=getattr(worker, "pid", None))
            startup_timeout = (
                args.startup_timeout
                if args.startup_timeout is not None
                else (120 if args.load or scenario_path else 20)
            )
            print(
                (
                    "Restoring saved residents..."
                    if args.load
                    else "Starting persistent residents..."
                ),
                flush=True,
            )
            ready = _read_ready(
                worker, startup_timeout, cancelled=lambda: viewer.poll() is not None
            )
            run_log.event(
                "worker_ready", duration_seconds=time.monotonic() - worker_started
            )
            port = ready["port"]
            viewer_options += [
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--token",
                token,
            ]
        print("San Francisco: loading the city and resident simulation.", flush=True)
        if viewer is None:
            viewer = _start_viewer(
                runtime + ["--"] + viewer_options, runtime_environment, run_log
            )
            if hardware_monitor is not None:
                hardware_monitor.register_process(
                    getattr(viewer, "pid", None), "viewer"
                )
        else:
            write_status(
                startup_path, "ready", "Loading San Francisco", arguments=viewer_options
            )
        run_log.event("viewer_handoff_completed", replay=bool(args.replay))
        run_log.update(status="running")
        started = time.monotonic()
        while viewer.poll() is None:
            if worker is not None and worker.poll() is not None:
                raise RuntimeError(
                    f"Simulation worker stopped unexpectedly; see {log_path}"
                )
            if (
                args.smoke_test
                or args.screenshot
                or args.workspace_probe
                or args.menu_probe
            ) and time.monotonic() - started > args.smoke_timeout:
                raise RuntimeError(
                    "Godot verification did not finish before its timeout"
                )
            time.sleep(0.1)
        run_log.close_capture(source="viewer")
        exit_code = viewer.returncode
        if exit_code != 0 or run_log.has_errors:
            run_status = "failed"
            exit_code = exit_code or 1
            run_log.error(
                (
                    f"Godot exited with code {viewer.returncode}"
                    if viewer.returncode != 0
                    else "Godot reported an application error before closing"
                ),
                source="viewer",
            )
        elif run_log.startup_complete:
            run_status = "completed"
        else:
            run_status = "cancelled"
    except _LaunchCancelled:
        exit_code = viewer.returncode if viewer is not None else 0
        run_status = "cancelled" if exit_code == 0 else "failed"
        run_log.event("startup_cancelled")
    except (OSError, RuntimeError, ValueError) as error:
        run_log.error(str(error))
        print(f"City Hall could not run: {error}", file=sys.stderr)
        if log_path and log_path.is_file():
            # Worker logs never contain the launch token. Show bounded diagnostics.
            if worker_log:
                worker_log.flush()
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            if detail.strip():
                run_log.error(detail, source="worker")
                print(detail, file=sys.stderr)
        if startup_path is not None and viewer is not None and viewer.poll() is None:
            try:
                write_status(startup_path, "error", str(error))
                if worker is not None:
                    early_worker_cleanup = _cleanup_stage(
                        run_log, "worker", lambda: _shutdown_worker(worker, port, token)
                    )
                if not (
                    args.headless
                    or args.smoke_test
                    or args.screenshot
                    or args.workspace_probe
                    or args.menu_probe
                ):
                    while viewer.poll() is None:
                        time.sleep(0.1)
            except (OSError, RuntimeError):
                pass
        exit_code = 1
    except KeyboardInterrupt:
        run_status = "interrupted"
        exit_code = 130
        run_log.event("keyboard_interrupt")
    except Exception as error:
        run_log.error(f"{type(error).__name__}: {error}")
        raise
    finally:
        cleanup_outcomes = []
        if viewer is not None:
            cleanup_outcomes.append(
                _cleanup_stage(run_log, "viewer", lambda: _terminate_tree(viewer))
            )
        if worker is not None:
            outcome = early_worker_cleanup
            if outcome is None or worker.poll() is None:
                outcome = _cleanup_stage(
                    run_log, "worker", lambda: _shutdown_worker(worker, port, token)
                )
            cleanup_outcomes.append(outcome)
            if worker.stdout:
                cleanup_outcomes.append(
                    _cleanup_stage(run_log, "worker_stdout", worker.stdout.close)
                )
        if startup_path is not None:
            cleanup_outcomes.append(
                _cleanup_stage(
                    run_log,
                    "startup_handoff",
                    lambda: startup_path.unlink(missing_ok=True),
                )
            )
        cleanup_outcomes.append(
            _cleanup_stage(run_log, "output_capture", run_log.close_capture)
        )
        if worker_log:
            cleanup_outcomes.append(
                _cleanup_stage(run_log, "worker_archive", worker_log.close)
            )
        if hardware_monitor is not None:
            cleanup_outcomes.append(
                _cleanup_stage(
                    run_log, "hardware", lambda: _stop_monitor(hardware_monitor)
                )
            )
        if telemetry is not None:
            cleanup_outcomes.append(
                _cleanup_stage(run_log, "telemetry", lambda: _stop_monitor(telemetry))
            )
        incomplete = any(
            item.get("status") in ("failed", "forced", "timed_out")
            or item.get("exit_code") not in (None, 0)
            for item in cleanup_outcomes
        )
        if run_status != "interrupted" and (
            run_log.has_errors or (incomplete and run_status == "completed")
        ):
            run_status, exit_code = "failed", exit_code or 1
        try:
            persistence = run_log.finish(
                run_status,
                exit_code,
                viewer_exit_code=getattr(viewer, "returncode", None),
                worker_exit_code=getattr(worker, "returncode", None),
            )
        except Exception as error:
            persistence = {"persisted": False, "reason": type(error).__name__}
        if not persistence.get("persisted", False):
            print(
                "San Francisco: final run log was not saved; cleanup already attempted.",
                file=sys.stderr,
            )
            if run_status != "interrupted":
                exit_code = exit_code or 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
