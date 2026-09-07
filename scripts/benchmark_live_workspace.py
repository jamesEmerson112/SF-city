"""Run real launcher/viewer population experiments and retain local evidence.

This measures exploratory population transitions plus paired console visibility
at a paused state. It never equates the explored counts with supported capacity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--mode", choices=("map", "overhead", "follow"), default="map")
    result.add_argument("--counts", default="200,500,1000,2000,5000")
    result.add_argument("--seconds", type=float, default=3.0)
    result.add_argument("--timeout", type=float, default=900.0)
    result.add_argument("--load", type=Path)
    result.add_argument("--city", action="store_true")
    result.add_argument("--layouts", action="store_true")
    result.add_argument("--headless", action="store_true")
    result.add_argument(
        "--reject-count",
        type=int,
        help="Verify an expected route-budget rejection after the measured populations",
    )
    result.add_argument("--output", type=Path)
    return result


def summarize(report: dict) -> dict:
    measurements = report.get("measurements", [])
    populations = sorted({item["population"] for item in measurements})
    outcomes = []
    for population in populations:
        values = [item for item in measurements if item["population"] == population]
        pairs = []
        for pair in sorted({item["pair"] for item in values}):
            matched = {
                item["console_open"]: item for item in values if item["pair"] == pair
            }
            if set(matched) != {False, True}:
                continue
            closed = matched[False]["metrics"].get("performance", {}).get("p95_ms")
            opened = matched[True]["metrics"].get("performance", {}).get("p95_ms")
            if not all(
                isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                for value in (closed, opened)
            ):
                continue
            pairs.append(
                {
                    "pair": pair,
                    "closed_p95_ms": closed,
                    "open_p95_ms": opened,
                    "difference_ms": opened - closed,
                    "difference_percent": (opened - closed) / closed * 100,
                }
            )
        outcomes.append(
            {
                "population": population,
                "pairs": pairs,
                "median_paired_p95_difference_ms": (
                    statistics.median(item["difference_ms"] for item in pairs)
                    if pairs
                    else None
                ),
                "measurement": (
                    "Median of paired changes in callback-interval p95; "
                    "not a pooled frame percentile or GPU execution time."
                ),
            }
        )
    return {
        "schema_version": 1,
        "status": report.get("status", "incomplete"),
        "rendered": report.get("rendered"),
        "renderer": report.get("renderer"),
        "map_view_held_fixed": report.get("map_view_held_fixed", False),
        "graphics_adapter": report.get("graphics_adapter"),
        "measurement_seconds_requested": report.get("measurement_seconds_requested"),
        "populations": outcomes,
        "all_counts_have_three_valid_pairs": bool(outcomes)
        and all(len(item["pairs"]) == 3 for item in outcomes),
        "checks": report.get("checks", []),
        "limitations": [
            "Population transitions are exploratory; the real day continues when unpaused.",
            "Console pairs hold the paused cohort, view, and hardware sampling constant.",
            "Short samples and background machine activity can dominate small differences.",
            "Requested layouts and actual physical window sizes are recorded separately.",
            "No interactive population capacity is inferred from successful completion.",
        ],
    }


def source_hashes(interpreter: Path, checkpoint: Path | None) -> dict[str, str]:
    paths = list((ROOT / "civic_center").glob("*.py"))
    paths += [
        path
        for path in (ROOT / "viewer").glob("*.gd")
        if not path.name.endswith("_tests.gd")
    ]
    paths += [ROOT / "viewer/project.godot", Path(__file__).resolve()]
    fingerprints = {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }
    # Resolve the same optional runtimes as the launcher. Public evidence uses
    # logical names instead of exposing local installation or checkpoint paths.
    sys.path.insert(0, str(ROOT))
    try:
        from civic_center.launch import find_godot
        from civic_center.native_routing import find_library
        from civic_center.package_verify import file_hash

        binaries = {
            "runtime/python": interpreter,
            "runtime/godot": Path(find_godot()),
            "runtime/routing": find_library(),
            "runtime/crowd": ROOT / "viewer/native/bin/civic_godot.dll",
            "runtime/crowd_descriptor": ROOT / "viewer/native/civic_godot.gdextension",
            "input/checkpoint": checkpoint,
        }
        for label, path in binaries.items():
            if path is not None and Path(path).is_file():
                with Path(path).open("rb") as stream:
                    fingerprints[label] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
    finally:
        sys.path.pop(0)
    return fingerprints


def public_command(command: list[str]) -> list[str]:
    """Retain reproducible options without local installation or data paths."""
    result = ["<python>"]
    replacements = {
        "--load": "<checkpoint>",
        "--workspace-probe": "<evidence>/viewer-report.json",
        "--log-dir": "<evidence>/run-logs",
    }
    for index, value in enumerate(command[1:], start=1):
        result.append(
            replacements.get(
                command[index - 1], value.replace(str(ROOT), "<repository>")
            )
        )
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
    args = parser().parse_args(argv)
    try:
        counts = [int(value) for value in args.counts.split(",")]
    except ValueError:
        raise SystemExit("--counts must be a comma-separated list of integers")
    if (
        not counts
        or any(not 1 <= value <= 5000 for value in counts)
        or (args.reject_count is not None and not 1 <= args.reject_count <= 5000)
        or not math.isfinite(args.seconds)
        or args.seconds <= 0
        or not math.isfinite(args.timeout)
        or args.timeout <= 0
    ):
        raise SystemExit("Counts must be 1-5000 and durations finite and positive")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = (
        args.output or ROOT / ".cache" / "live-workspace" / f"{stamp}-{args.mode}"
    ).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    report_path = directory / "viewer-report.json"
    if report_path.exists():
        raise SystemExit(
            "Output already contains a viewer report; choose a new directory"
        )
    interpreter = ROOT / "venv" / "Scripts" / "python.exe"
    if not interpreter.is_file():
        interpreter = Path(sys.executable)
    command = [
        str(interpreter),
        "-m",
        "civic_center",
        "--population",
        "200",
        "--mode",
        args.mode,
        "--lighting",
        "fixed",
        "--window-size",
        "1440x900",
        "--window-mode",
        "windowed",
        "--ui-scale",
        "1",
        "--no-display-settings",
        "--workspace-probe",
        str(report_path),
        "--probe-counts",
        ",".join(map(str, counts)),
        "--probe-seconds",
        str(args.seconds),
        "--smoke-timeout",
        str(args.timeout),
        "--log-dir",
        str(directory / "run-logs"),
    ]
    if args.load:
        command += ["--load", str(args.load.resolve())]
    elif args.city:
        command += ["--world", "city"]
    else:
        command += ["--world", "pilot", "--no-geography"]
    if args.layouts:
        command.append("--probe-layouts")
    if args.headless:
        command.append("--headless")
    print(f"Evidence: {directory}", flush=True)
    environment = os.environ.copy()
    environment.pop("CIVIC_WORKSPACE_REJECT_COUNT", None)
    if args.reject_count is not None:
        environment["CIVIC_WORKSPACE_REJECT_COUNT"] = str(args.reject_count)
    hashes_before = source_hashes(interpreter, args.load)
    started = time.monotonic()
    with (directory / "launcher-output.log").open("wb") as output:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            exit_code = process.wait(timeout=args.timeout + 30)
        except subprocess.TimeoutExpired:
            terminate_owned(process)
            exit_code = 124
        finally:
            if process.poll() is None:
                terminate_owned(process)
    hashes_after = source_hashes(interpreter, args.load)
    result = {
        "schema_version": 1,
        "source_hashes": hashes_before,
        "source_changed_during_run": hashes_before != hashes_after,
        "exit_code": exit_code,
        "duration_seconds": time.monotonic() - started,
        "command": public_command(command),
        "expected_rejection_target": args.reject_count,
    }
    if report_path.is_file():
        raw = report_path.read_bytes()
        report = json.loads(raw)
        result["viewer_report_sha256"] = hashlib.sha256(raw).hexdigest()
        result["summary"] = summarize(report)
    expected_rejections = {
        item["message"]
        for item in result.get("summary", {}).get("checks", [])
        if item.get("check") == "oversized_population_rejected_without_state_change"
        and item.get("requested_population") == args.reject_count
    }
    log_reports = []
    for log_path in sorted((directory / "run-logs").glob("*.json")):
        raw_log = log_path.read_bytes()
        log = json.loads(raw_log)
        diagnostics = log.get("diagnostics", {})
        observed_errors = diagnostics.get("errors", [])
        expected_error_count = sum(
            error.get("message") in expected_rejections for error in observed_errors
        )
        error_count = diagnostics.get("error_count", len(observed_errors))
        log_reports.append(
            {
                "file": log_path.relative_to(directory).as_posix(),
                "sha256": hashlib.sha256(raw_log).hexdigest(),
                "status": log.get("status"),
                "errors": error_count,
                "expected_rejection_errors": expected_error_count,
                "unexpected_errors": error_count - expected_error_count,
                "hardware_errors": log.get("hardware", {}).get("error_count", 0),
            }
        )
    result["run_logs"] = log_reports
    result["validation_valid"] = (
        exit_code == 0
        and result.get("summary", {}).get("status") == "passed"
        and result.get("summary", {}).get("all_counts_have_three_valid_pairs", False)
        and (args.reject_count is None or bool(expected_rejections))
        and not result["source_changed_during_run"]
        and bool(log_reports)
        and all(
            log["status"] == "completed" and log["unexpected_errors"] == 0
            for log in log_reports
        )
    )
    result["comparisons_valid"] = result["validation_valid"] and bool(
        result.get("summary", {}).get("rendered")
    )
    (directory / "summary.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "exit_code": exit_code,
                "status": result.get("summary", {}).get("status", "no_report"),
                "seconds": round(result["duration_seconds"], 2),
                "validation_valid": result["validation_valid"],
                "comparisons_valid": result["comparisons_valid"],
                "evidence": str(directory),
            }
        ),
        flush=True,
    )
    return exit_code or (0 if result["validation_valid"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
