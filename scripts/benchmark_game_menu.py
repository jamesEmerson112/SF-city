"""Exercise the rendered Escape menu and real launcher cleanup in isolated saves.

Timings are functional observations, not a before/after optimization benchmark.
Raw reports stay under .cache; no existing game save is replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def fingerprints(root: Path, interpreter: Path) -> dict[str, str]:
    paths = list((root / "civic_center").glob("*.py"))
    paths += list((root / "viewer").glob("*.gd"))
    paths += [root / "viewer/project.godot"]
    result = {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}
    result["runtime/python"] = digest(interpreter)
    return result


def terminate_owned(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
            check=False,
        )
    else:
        process.terminate()
    process.wait(timeout=15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["overhead", "map"], default="overhead")
    parser.add_argument(
        "--case",
        choices=["save_exit", "window_close", "save_error", "population_exit"],
        default="save_exit",
    )
    parser.add_argument("--population", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument(
        "--load", type=Path, help="Use a real saved city for the exit trial"
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.population <= 5000 or not 1 <= args.timeout <= 3600:
        parser.error("Population must be 1..5000 and timeout 1..3600 seconds.")
    root = (args.package_root or ROOT).resolve()
    interpreter = (
        root / "runtime/python/python.exe"
        if args.package_root
        else root / "venv/Scripts/python.exe"
    )
    if not interpreter.is_file():
        raise SystemExit(f"Missing interpreter: {interpreter}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = (
        args.output or ROOT / ".cache/game-menu" / f"{stamp}-{args.mode}-{args.case}"
    ).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise SystemExit(
            "Choose an empty output directory; existing evidence is preserved."
        )
    saves = directory / "saves"
    saves.mkdir()
    quick = saves / "quick.json"
    quick.write_text(
        '{"test_sentinel":"preserve existing quick save"}\n', encoding="utf-8"
    )
    quick_hash = digest(quick)
    recovery = saves / "exit-recovery.json"
    if args.case == "save_error":
        recovery.mkdir()
    report_path = directory / "viewer-report.json"
    command = [
        str(interpreter),
        "-m",
        "civic_center",
        "--world",
        "pilot",
        "--no-geography",
        "--population",
        str(args.population),
        "--seed",
        "7",
        "--mode",
        args.mode,
        "--lighting",
        "fixed",
        "--window-size",
        "1280x720",
        "--window-mode",
        "windowed",
        "--ui-scale",
        "1",
        "--no-display-settings",
        "--save-dir",
        str(saves),
        "--log-dir",
        str(directory / "run-logs"),
        "--menu-probe",
        str(report_path),
        "--menu-probe-case",
        args.case,
        "--smoke-timeout",
        str(args.timeout),
    ]
    if args.load:
        command.remove("--no-geography")
        world_index = command.index("--world")
        del command[world_index : world_index + 2]
        command += ["--load", str(args.load.resolve())]
    if args.headless:
        command.append("--headless")
    before = fingerprints(root, interpreter)
    if args.load:
        before["input/checkpoint"] = digest(args.load)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    observed_processes: dict[int, float] = {}
    import psutil

    with (directory / "launcher-output.log").open("wb") as output:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = started + args.timeout + 30
        timed_out = False
        try:
            while process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    for child in [parent, *parent.children(recursive=True)]:
                        try:
                            observed_processes[child.pid] = child.create_time()
                        except psutil.Error:
                            pass
                except psutil.Error:
                    pass
                if time.monotonic() >= deadline:
                    timed_out = True
                    terminate_owned(process)
                    break
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                terminate_owned(process)
    elapsed = time.monotonic() - started
    remaining = []
    for pid, created in observed_processes.items():
        try:
            child = psutil.Process(pid)
            if child.create_time() == created and child.is_running():
                remaining.append(pid)
        except psutil.Error:
            pass
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.is_file()
        else {}
    )
    logs = []
    for path in sorted((directory / "run-logs").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        logs.append(
            {
                "file": path.relative_to(directory).as_posix(),
                "sha256": digest(path),
                "status": data.get("status"),
                "exit_code": data.get("exit_code"),
                "exit": data.get("exit", {}),
                "cleanup": data.get("cleanup", {}),
                "diagnostics": data.get("diagnostics", {}),
                "hardware_status": data.get("hardware", {}).get("status"),
                "runtime": data.get("metrics", {}).get("runtime", {}),
            }
        )
    reload_result = None
    if recovery.is_file():
        reload_script = (
            "import json,sys; from civic_center.checkpoint import load_checkpoint; "
            "s=load_checkpoint(sys.argv[1]); "
            "print(json.dumps({'tick':s.tick,'paused':s.paused,'speed':s.speed,"
            "'population':len(s._residents),'roster_revision':s.roster_revision}))"
        )
        checked = subprocess.run(
            [str(interpreter), "-c", reload_script, str(recovery)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if checked.returncode == 0:
            reload_result = json.loads(checked.stdout.strip().splitlines()[-1])
        else:
            reload_result = {"error": "Recovery checkpoint could not be loaded."}
    expected_population = int(report.get("initial_population", args.population)) + (
        1 if args.case == "population_exit" else 0
    )
    save_valid = (
        recovery.is_dir() and reload_result is None
        if args.case == "save_error"
        else (
            isinstance(reload_result, dict)
            and reload_result.get("paused") is True
            and reload_result.get("population") == expected_population
        )
    )
    save_response = report.get("save_response", {})
    if args.case != "save_error":
        save_valid = bool(
            save_valid
            and save_response.get("type") == "ack"
            and save_response.get("action") == "save"
            and save_response.get("slot") == "exit-recovery"
            and save_response.get("captured_tick") == reload_result.get("tick")
        )
    exit_record = logs[0]["exit"] if len(logs) == 1 else {}
    expected_outcome = "skipped" if args.case == "save_error" else "saved"
    stages = logs[0]["cleanup"].get("stages", {}) if len(logs) == 1 else {}
    worker_outcome = stages.get("worker", {})
    capture_outcome = stages.get("output_capture", {})
    after = fingerprints(root, interpreter)
    if args.load:
        after["input/checkpoint"] = digest(args.load)
    checks = {
        "launcher_completed": process.returncode == 0 and not timed_out,
        "viewer_passed": report.get("status") == "passed",
        "quick_save_unchanged": digest(quick) == quick_hash,
        "recovery_valid": bool(save_valid),
        "exit_record_matches": exit_record.get("save_outcome") == expected_outcome
        and (
            expected_outcome != "saved"
            or exit_record.get("captured_tick") == save_response.get("captured_tick")
        ),
        "worker_shutdown_acknowledged": (
            worker_outcome.get("status") == "graceful"
            and worker_outcome.get("acknowledged") is True
            and worker_outcome.get("exit_code") == 0
        ),
        "output_fully_drained": capture_outcome.get("drained") is True,
        "final_viewer_metrics": len(logs) == 1
        and logs[0]["runtime"].get("final") is True,
        "valid_single_exit_marker": bool(logs)
        and all(
            row["diagnostics"].get("duplicate_exit_marker_count", 0) == 0
            and row["diagnostics"].get("malformed_marker_count", 0) == 0
            for row in logs
        ),
        "owned_processes_stopped": not remaining,
        "source_unchanged": before == after,
        "one_completed_run": len(logs) == 1 and logs[0]["status"] == "completed",
        "no_application_errors": bool(logs)
        and all(row["diagnostics"].get("error_count", 0) == 0 for row in logs),
    }
    result = {
        "schema_version": 1,
        "case": args.case,
        "mode": args.mode,
        "population": int(report.get("initial_population", args.population)),
        "loaded_checkpoint": args.load is not None,
        "portable": bool(args.package_root),
        "started_at": started_at,
        "exit_code": process.returncode,
        "duration_seconds": elapsed,
        "timing_boundary": "before launcher spawn through observed launcher exit; includes 250 ms process polling",
        "checks": checks,
        "validation_valid": all(checks.values()),
        "source_hashes": before,
        "source_changed_during_run": before != after,
        "viewer": report,
        "run_logs": logs,
        "recovery": reload_result,
        "remaining_owned_processes": remaining,
        "raw_evidence": str(directory),
    }
    (directory / "summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "case": args.case,
                "mode": args.mode,
                "seconds": round(elapsed, 3),
                "validation_valid": result["validation_valid"],
                "checks": checks,
                "evidence": str(directory),
            }
        ),
        flush=True,
    )
    return 0 if result["validation_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
