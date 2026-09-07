"""Atomic, bounded JSON checkpoints for deterministic schedules and live rosters.

Versions 1 and 2 retain their fixed-scenario restore paths. Version 3 adds the
current roster revision, monotonic identity allocator, join ticks, exact resident
runtime records and future event queue. Restore validates each resident against
its current schedule phase in at most one commute cycle, then restores the saved
bounded journal and counter; it does not replay an unbounded population history.

Versions 2 and 3 store the scenario as zlib-json-v1 with declared expanded size,
SHA-256 and bounded base64 chunks. The physical file and expanded scenario/state
have separate 64 MiB limits. Runtime records share the expanded five-million-value
budget in v3. Route and complete metadata digests verify exact reconstruction.
No checkpoint accepts Python objects or executable code. Older scenarios retain
their original route geometry; loading never regenerates geography.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import tempfile
import weakref
import zlib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import CivicSimulation
from .scenario import scenario_hash

CHECKPOINT_VERSION = 2
LIVE_CHECKPOINT_VERSION = 3
LIVE_RECONSTRUCTION_MODE = "live-roster-v1"
RECONSTRUCTION_MODE = "deterministic-scenario-v1"
# Limits apply independently to the physical file and expanded scenario plus
# dynamic state. Compression never permits unlimited allocation or hidden trees.
# The JSON value budget also counts expanded data, not just its encoded envelope.
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
MAX_SCENARIO_BYTES = 64 * 1024 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_CONTAINER_ITEMS = 50_000
MAX_JSON_VALUES = 5_000_000
MAX_JSON_DEPTH = 32
MAX_STRING_LENGTH = 65_536

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DOCUMENT_FIELDS = {
    "checkpoint_version",
    "reconstruction_mode",
    "scenario",
    "scenario_sha256",
    "tick",
    "paused",
    "speed",
    "state",
    "state_sha256",
    "sha256",
}
_STATE_FIELDS = {
    "tick",
    "simulation_time",
    "clock_seconds",
    "paused",
    "speed",
    "residents",
    "buildings",
    "events",
    "event_count",
}
_DAILY_STATE_FIELDS = {"day_index", "day_seconds"}
_SCENARIO_ENCODING = "zlib-json-v1"
_SCENARIO_FIELDS = {"encoding", "uncompressed_bytes", "json_sha256", "chunks"}
_VERIFICATION_FIELDS = {"metadata_state_sha256", "trip_geometry_sha256"}
_COMPRESSED_CHUNK_BYTES = 49_152  # Base64 expands this to one 65,536-character string.


@dataclass(frozen=True, slots=True)
class PreparedCheckpointCapture:
    """One immutable scenario encoding tied to a specific live model.

    Preparation freezes the scenario at this point. Changing assignments or
    scenario metadata afterward requires a new preparation. Live roster commits
    install freshly prepared bytes and increment the checked roster revision. The weak
    reference is checked only on the main loop and is never sent to the writer.
    """

    scenario_json: bytes
    _simulation: weakref.ReferenceType[CivicSimulation]
    roster_revision: int = 0


@dataclass(frozen=True, slots=True)
class CheckpointCapture:
    """Detached immutable values safe to hand to a background checkpoint job."""

    scenario_json: bytes
    state_json: bytes
    tick: int
    paused: bool
    speed: float
    runtime_json: bytes | None = None


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError(f"Checkpoint contains invalid JSON data: {error}") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_tree(value: Any, *, initial_values: int = 0) -> int:
    """Bound nesting/container sizes and reject non-JSON or nonfinite values."""
    pending = [(value, 0)]
    visited = initial_values
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > MAX_JSON_VALUES:
            raise ValueError("Checkpoint contains too many JSON values")
        if depth > MAX_JSON_DEPTH:
            raise ValueError("Checkpoint JSON nesting is too deep")
        if current is None or type(current) is bool:
            continue
        if type(current) is int:
            if abs(current) > MAX_SAFE_INTEGER:
                raise ValueError("Checkpoint integer exceeds the JSON-safe range")
        elif type(current) is float:
            if not math.isfinite(current):
                raise ValueError("Checkpoint numbers must be finite")
        elif type(current) is str:
            if len(current) > MAX_STRING_LENGTH:
                raise ValueError("Checkpoint string is too long")
            try:
                current.encode("utf-8")
            except UnicodeError as error:
                raise ValueError(
                    "Checkpoint strings must contain valid Unicode"
                ) from error
        elif type(current) in (list, dict):
            if len(current) > MAX_CONTAINER_ITEMS:
                raise ValueError("Checkpoint container is too large")
            if isinstance(current, dict):
                for key, child in current.items():
                    if type(key) is not str:
                        raise ValueError("Checkpoint object keys must be strings")
                    pending.append((key, depth + 1))
                    pending.append((child, depth + 1))
            else:
                pending.extend((child, depth + 1) for child in current)
        else:
            raise ValueError(
                f"Checkpoint contains a non-JSON value: {type(current).__name__}"
            )

    return visited


def _nonnegative_integer(value: Any, description: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
        raise ValueError(
            f"Checkpoint {description} must be a nonnegative JSON-safe integer"
        )
    return value


def _finite_number(value: Any, description: str, positive: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Checkpoint {description} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"Checkpoint {description} must be positive")
    return float(value)


def _records(value: Any, description: str) -> list[dict[str, Any]]:
    if type(value) is not list or any(type(record) is not dict for record in value):
        raise ValueError(f"Checkpoint {description} must be an array of objects")
    return value


def _checksum(value: Any, description: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"Checkpoint {description} must be a lowercase SHA-256 digest")
    return value


def _encode_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    _validate_tree(scenario)
    encoded = _canonical(scenario)
    if len(encoded) > MAX_SCENARIO_BYTES:
        raise ValueError(
            f"Checkpoint expanded scenario exceeds {MAX_SCENARIO_BYTES} bytes"
        )
    compressed = zlib.compress(encoded, level=6)
    return {
        "encoding": _SCENARIO_ENCODING,
        "uncompressed_bytes": len(encoded),
        "json_sha256": hashlib.sha256(encoded).hexdigest(),
        "chunks": [
            base64.b64encode(
                compressed[offset : offset + _COMPRESSED_CHUNK_BYTES]
            ).decode("ascii")
            for offset in range(0, len(compressed), _COMPRESSED_CHUNK_BYTES)
        ],
    }


def _decode_scenario(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _SCENARIO_FIELDS:
        raise ValueError(
            "Checkpoint compressed scenario has missing or unsupported fields"
        )
    if value["encoding"] != _SCENARIO_ENCODING:
        raise ValueError("Unsupported checkpoint scenario encoding")
    size = _nonnegative_integer(value["uncompressed_bytes"], "expanded scenario size")
    if not 0 < size <= MAX_SCENARIO_BYTES:
        raise ValueError(
            f"Checkpoint expanded scenario exceeds {MAX_SCENARIO_BYTES} bytes or is empty"
        )
    _checksum(value["json_sha256"], "scenario JSON checksum")
    chunks = value["chunks"]
    if (
        type(chunks) is not list
        or not chunks
        or any(type(chunk) is not str or not chunk for chunk in chunks)
    ):
        raise ValueError(
            "Checkpoint compressed scenario chunks must be nonempty strings"
        )
    try:
        compressed = b"".join(
            base64.b64decode(chunk, validate=True) for chunk in chunks
        )
    except (ValueError, binascii.Error) as error:
        raise ValueError(
            "Checkpoint compressed scenario contains invalid base64"
        ) from error
    decoder = zlib.decompressobj()
    try:
        # The extra byte detects a dishonest size without inflating the rest of a
        # compressed bomb. Do not call unbounded decompress() or flush() here.
        encoded = decoder.decompress(compressed, size + 1)
    except zlib.error as error:
        raise ValueError(f"Invalid checkpoint compressed scenario: {error}") from error
    if len(encoded) != size or decoder.unconsumed_tail:
        raise ValueError(
            "Checkpoint expanded scenario size does not match its declaration"
        )
    if not decoder.eof:
        raise ValueError("Checkpoint compressed scenario stream is truncated")
    if decoder.unused_data:
        raise ValueError(
            "Checkpoint compressed scenario has trailing or concatenated streams"
        )
    if hashlib.sha256(encoded).hexdigest() != value["json_sha256"]:
        raise ValueError(
            "Checkpoint scenario JSON checksum does not match expanded contents"
        )
    try:
        return json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(
            f"Invalid expanded checkpoint scenario JSON: {error}"
        ) from error


def _state_verification(simulation: CivicSimulation) -> dict[str, Any]:
    """Cover every full-snapshot field without materializing all trip copies.

    Geometry hashes include future vertices as well as the current segment, so a
    different equal-length path cannot pass just because its present pose agrees.
    Definitions are detached and hashed one at a time, bounding temporary memory.
    """
    state = simulation.snapshot(include_trip_geometry=False)
    trip_hashes = {}
    for resident in state["residents"]:
        trip = resident["trip"]
        if trip is not None:
            geometry = simulation.trip_geometries([trip["id"]])[0]
            del geometry["id"]
            trip_hashes[trip["id"]] = _digest(geometry)
    return {
        "metadata_state_sha256": _digest(state),
        "trip_geometry_sha256": trip_hashes,
    }


def _validate_document(document: Any) -> dict[str, Any]:
    _validate_tree(document)
    if type(document) is not dict:
        raise ValueError("Checkpoint object has missing or unsupported fields")
    version = document.get("checkpoint_version")
    if type(version) is not int or version not in (
        1,
        CHECKPOINT_VERSION,
        LIVE_CHECKPOINT_VERSION,
    ):
        raise ValueError(
            "Checkpoint has unsupported checkpoint_version; expected 1, 2, or 3"
        )
    fields = _DOCUMENT_FIELDS | {"verification"} if version >= 2 else _DOCUMENT_FIELDS
    if version == 3:
        fields = fields | {"runtime"}
    if set(document) != fields:
        raise ValueError("Checkpoint object has missing or unsupported fields")
    expected_mode = LIVE_RECONSTRUCTION_MODE if version == 3 else RECONSTRUCTION_MODE
    if document["reconstruction_mode"] != expected_mode:
        raise ValueError("Unsupported checkpoint reconstruction_mode")
    tick = _nonnegative_integer(document["tick"], "tick")
    if type(document["paused"]) is not bool:
        raise ValueError("Checkpoint paused must be a boolean")
    _finite_number(document["speed"], "speed", positive=True)
    for field in ("sha256", "scenario_sha256", "state_sha256"):
        _checksum(document[field], field)
    actual_digest = _digest(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    if document["sha256"] != actual_digest:
        raise ValueError("Checkpoint checksum does not match its contents")
    scenario = (
        _decode_scenario(document["scenario"]) if version >= 2 else document["scenario"]
    )
    if version >= 2:
        proof = document["verification"]
        if type(proof) is not dict or set(proof) != _VERIFICATION_FIELDS:
            raise ValueError(
                "Checkpoint verification has missing or unsupported fields"
            )
        _checksum(proof["metadata_state_sha256"], "metadata state checksum")
        geometry_hashes = proof["trip_geometry_sha256"]
        if type(geometry_hashes) is not dict:
            raise ValueError("Checkpoint trip geometry checksums must be an object")
        for digest in geometry_hashes.values():
            _checksum(digest, "trip geometry checksum")
        if (
            document["scenario"]["uncompressed_bytes"]
            + len(_canonical(document["state"]))
            + (len(_canonical(document["runtime"])) if version == 3 else 0)
            > MAX_SCENARIO_BYTES
        ):
            raise ValueError(
                f"Checkpoint expanded scenario and state exceed {MAX_SCENARIO_BYTES} bytes"
            )
        expanded = {
            "scenario": scenario,
            "state": document["state"],
            "verification": proof,
        }
        if version == 3:
            expanded["runtime"] = document["runtime"]
        _validate_tree(expanded)
    if (
        type(scenario) is not dict
        or type(scenario.get("schema_version")) is not int
        or scenario["schema_version"] != 1
    ):
        raise ValueError("Checkpoint scenario schema_version must be 1")
    if _nonnegative_integer(scenario.get("tick_hz"), "scenario tick_hz") == 0:
        raise ValueError("Checkpoint scenario tick_hz must be positive")
    _finite_number(scenario.get("start_time_seconds", 0), "scenario start_time_seconds")
    for field in ("nodes", "edges", "buildings", "residents"):
        _records(scenario.get(field), f"scenario {field}")
    actual_scenario_hash = scenario_hash(scenario)
    if document["scenario_sha256"] != actual_scenario_hash:
        raise ValueError("Checkpoint scenario checksum does not match its contents")
    if (
        "sha256" in scenario
        and _checksum(scenario["sha256"], "embedded scenario sha256")
        != actual_scenario_hash
    ):
        raise ValueError(
            "Checkpoint embedded scenario checksum does not match its contents"
        )
    for resident in scenario["residents"]:
        _nonnegative_integer(resident.get("departure_tick"), "resident departure_tick")
        _nonnegative_integer(resident.get("return_tick"), "resident return_tick")
        _finite_number(resident.get("speed_mps"), "resident speed_mps", positive=True)
    state = document["state"]
    daily = scenario.get("schedule") == {"mode": "daily-v1"}
    state_fields = _STATE_FIELDS | _DAILY_STATE_FIELDS if daily else _STATE_FIELDS
    if type(state) is not dict or set(state) != state_fields:
        raise ValueError("Checkpoint state has missing or unsupported fields")
    if document["state_sha256"] != _digest(state):
        raise ValueError("Checkpoint state checksum does not match its contents")
    if _nonnegative_integer(state["tick"], "state tick") != tick:
        raise ValueError("Checkpoint state tick does not match checkpoint tick")
    if type(state["paused"]) is not bool or state["paused"] != document["paused"]:
        raise ValueError("Checkpoint state paused does not match checkpoint paused")
    if (
        _finite_number(state["speed"], "state speed", positive=True)
        != document["speed"]
    ):
        raise ValueError("Checkpoint state speed does not match checkpoint speed")
    _finite_number(state["simulation_time"], "state simulation_time")
    _finite_number(state["clock_seconds"], "state clock_seconds")
    if daily:
        day_index = state["day_index"]
        if type(day_index) is not int or abs(day_index) > MAX_SAFE_INTEGER:
            raise ValueError("Checkpoint day_index must be a JSON-safe integer")
        day_seconds = _finite_number(state["day_seconds"], "state day_seconds")
        if not 0 <= day_seconds < 86_400:
            raise ValueError("Checkpoint day_seconds must be within one day")
    _nonnegative_integer(state["event_count"], "state event_count")
    for field in ("residents", "buildings", "events"):
        _records(state[field], f"state {field}")
    if len(state["events"]) > 256:
        raise ValueError("Checkpoint event journal exceeds 256 records")
    # Preserve the signed wire envelope until validation is complete. Consumers
    # receive its full scenario; this normalized copy must never be re-signed.
    return dict(document, scenario=scenario)


def prepare_checkpoint_capture(
    simulation: CivicSimulation,
) -> PreparedCheckpointCapture:
    """Freeze scenario JSON once, preferably before a worker becomes ready.

    Candidate models can be prepared on their construction thread before being
    installed on the main loop. Subsequent captures only encode dynamic state.
    """
    if not isinstance(simulation, CivicSimulation):
        raise TypeError("prepare_checkpoint_capture requires a CivicSimulation")
    _validate_tree(simulation.scenario)
    encoded = _canonical(simulation.scenario)
    if len(encoded) > MAX_SCENARIO_BYTES:
        raise ValueError(f"Checkpoint scenario exceeds {MAX_SCENARIO_BYTES} bytes")
    return PreparedCheckpointCapture(
        encoded, weakref.ref(simulation), simulation.roster_revision
    )


def capture_checkpoint(
    simulation: CivicSimulation,
    prepared: PreparedCheckpointCapture | None = None,
) -> CheckpointCapture:
    """Capture one completed tick without later reading the live model.

    Call on the same loop that advances the model. A supplied preparation must
    belong to this model; it freezes the immutable scenario inputs explicitly.
    Reset, pause, speed changes and advancement after capture cannot alter it.
    """
    if not isinstance(simulation, CivicSimulation):
        raise TypeError("capture_checkpoint requires a CivicSimulation")
    if prepared is None:
        prepared = prepare_checkpoint_capture(simulation)
    if (
        not isinstance(prepared, PreparedCheckpointCapture)
        or prepared._simulation() is not simulation
    ):
        raise ValueError("Checkpoint preparation belongs to a different simulation")
    if prepared.roster_revision != simulation.roster_revision:
        raise ValueError("Checkpoint preparation has a stale roster revision")
    from .population import capture_runtime

    runtime = (
        _canonical(capture_runtime(simulation)) if simulation.roster_revision else None
    )
    state = simulation.snapshot(include_static=False, include_trip_geometry=False)
    return CheckpointCapture(
        prepared.scenario_json,
        _canonical(state),
        simulation.tick,
        simulation.paused,
        simulation.speed,
        runtime,
    )


def write_captured_checkpoint(capture: CheckpointCapture, path: str | Path) -> Path:
    """Reconstruct and validate a detached capture, then atomically write v2 or v3.

    This function may run in a background job. Its inputs contain only immutable
    bytes and scalar controls, never a live model or mutable scenario reference.
    """
    if not isinstance(capture, CheckpointCapture):
        raise TypeError("write_captured_checkpoint requires a CheckpointCapture")
    if (
        type(capture.scenario_json) is not bytes
        or type(capture.state_json) is not bytes
    ):
        raise ValueError("Checkpoint capture JSON must be immutable bytes")
    if capture.runtime_json is not None and type(capture.runtime_json) is not bytes:
        raise ValueError("Checkpoint runtime must be immutable JSON bytes")
    if (
        len(capture.scenario_json)
        + len(capture.state_json)
        + len(capture.runtime_json or b"")
        > MAX_SCENARIO_BYTES
    ):
        raise ValueError(
            f"Checkpoint expanded capture exceeds {MAX_SCENARIO_BYTES} bytes"
        )
    _nonnegative_integer(capture.tick, "capture tick")
    if type(capture.paused) is not bool:
        raise ValueError("Checkpoint capture paused must be a boolean")
    _finite_number(capture.speed, "capture speed", positive=True)
    try:
        scenario = json.loads(
            capture.scenario_json.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_constant,
        )
        _validate_tree(scenario)
        simulation = CivicSimulation(scenario)
        if capture.runtime_json is not None:
            from .population import restore_runtime

            runtime = json.loads(
                capture.runtime_json,
                object_pairs_hook=_unique_keys,
                parse_constant=_reject_constant,
            )
            state = json.loads(
                capture.state_json,
                object_pairs_hook=_unique_keys,
                parse_constant=_reject_constant,
            )
            _validate_tree({"runtime": runtime, "state": state})
            restore_runtime(simulation, runtime, state)
            if (
                simulation.tick != capture.tick
                or simulation.paused != capture.paused
                or simulation.speed != capture.speed
            ):
                raise ValueError("Live capture controls do not match state")
        else:
            simulation.step_ticks(capture.tick)
            simulation.set_paused(capture.paused)
            simulation.set_speed(capture.speed)
        reconstructed = simulation.snapshot(
            include_static=False, include_trip_geometry=False
        )
    except (
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ) as error:
        raise ValueError(
            f"Checkpoint capture could not be reconstructed: {error}"
        ) from error
    if _canonical(reconstructed) != capture.state_json:
        raise ValueError(
            "Checkpoint capture state does not match deterministic reconstruction"
        )
    return save_checkpoint(simulation, path)


def save_checkpoint(simulation: CivicSimulation, path: str | Path) -> Path:
    """Atomically save a complete checkpoint, preserving an existing save on error.

    Callers must serialize saves with simulation advancement (the worker does so
    on its event loop). A temporary sibling is flushed and fsynced before atomic
    replacement. This promises atomic file replacement, not immunity to every
    filesystem or hardware failure.
    """
    if not isinstance(simulation, CivicSimulation):
        raise TypeError("save_checkpoint requires a CivicSimulation")
    destination = Path(path)
    scenario = deepcopy(simulation.scenario)
    state = simulation.snapshot(include_static=False, include_trip_geometry=False)
    document = {
        "checkpoint_version": (
            LIVE_CHECKPOINT_VERSION
            if simulation.roster_revision
            else CHECKPOINT_VERSION
        ),
        "reconstruction_mode": (
            LIVE_RECONSTRUCTION_MODE
            if simulation.roster_revision
            else RECONSTRUCTION_MODE
        ),
        "scenario": _encode_scenario(scenario),
        "scenario_sha256": scenario_hash(scenario),
        "tick": simulation.tick,
        "paused": simulation.paused,
        "speed": simulation.speed,
        "state": state,
        "state_sha256": _digest(state),
        "verification": _state_verification(simulation),
    }
    if simulation.roster_revision:
        from .population import capture_runtime, restore_runtime

        document["runtime"] = capture_runtime(simulation)
        checked = CivicSimulation(scenario)
        restore_runtime(checked, document["runtime"], state)
        if _canonical(_state_verification(checked)) != _canonical(
            document["verification"]
        ):
            raise ValueError(
                "Live checkpoint route geometry does not match reconstruction"
            )
    document["sha256"] = _digest(document)
    _validate_document(document)
    encoded = _canonical(document) + b"\n"
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise ValueError(f"Checkpoint exceeds {MAX_CHECKPOINT_BYTES} bytes")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            # This is only the exact sibling file created above by this call.
            temporary.unlink(missing_ok=True)
    return destination


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Checkpoint JSON contains a duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Checkpoint JSON contains a nonfinite constant: {value}")


def load_checkpoint(path: str | Path) -> CivicSimulation:
    """Validate and reconstruct a new simulation without changing a live model."""
    source = Path(path)
    with source.open("rb") as stream:
        # The bounded read also handles a file that grows after opening it.
        encoded = stream.read(MAX_CHECKPOINT_BYTES + 1)
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise ValueError(f"Checkpoint exceeds {MAX_CHECKPOINT_BYTES} bytes")
    try:
        document = json.loads(
            encoded.decode("utf-8-sig"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f"Invalid checkpoint JSON: {error}") from error
    document = _validate_document(document)
    try:
        simulation = CivicSimulation(document["scenario"])
        live = document["checkpoint_version"] == LIVE_CHECKPOINT_VERSION
        if live:
            from .population import restore_runtime

            restore_runtime(simulation, document["runtime"], document["state"])
        else:
            simulation.step_ticks(document["tick"])
        compact = document["checkpoint_version"] >= 2
        reconstructed = simulation.snapshot(
            include_static=not compact, include_trip_geometry=not compact
        )
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise ValueError(
            f"Checkpoint scenario could not be reconstructed: {error}"
        ) from error
    # Compare JSON representations to distinguish booleans from integers and
    # preserve exact stored numeric forms; ordinary Python dict equality does not.
    expected = (
        document["state"] if live else dict(document["state"], paused=False, speed=1.0)
    )
    if _canonical(reconstructed) != _canonical(expected):
        raise ValueError("Checkpoint state does not match deterministic reconstruction")
    simulation.set_paused(document["paused"])
    simulation.set_speed(document["speed"])
    if compact and _canonical(_state_verification(simulation)) != _canonical(
        document["verification"]
    ):
        raise ValueError(
            "Checkpoint metadata or trip geometry does not match deterministic reconstruction"
        )
    return simulation
