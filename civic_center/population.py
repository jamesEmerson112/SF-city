"""Validated live roster changes; immutable routes and surviving state are retained."""

from __future__ import annotations

import copy
import heapq
import random
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

MIN_POPULATION = 1
MAX_POPULATION = 5000
LIVE_PREFIX = "live-resident-"


def validate_population(value: Any) -> int:
    if type(value) is not int or not MIN_POPULATION <= value <= MAX_POPULATION:
        raise ValueError(
            f"Population must be an integer from {MIN_POPULATION} to {MAX_POPULATION}"
        )
    return value


@dataclass(frozen=True)
class PopulationDelta:
    expected_revision: int
    target: int
    additions: tuple[dict, ...]
    removals: tuple[str, ...]
    next_identity: int


def world_identity(scenario: dict) -> str:
    import hashlib
    import json

    content = {
        "id": scenario.get("id"),
        "origin": scenario.get("origin"),
        "nodes": scenario.get("nodes"),
        "edges": scenario.get("edges"),
        "geography": scenario.get("geography_manifest_sha256"),
        "terrain": scenario.get("terrain_manifest"),
        "buildings": [
            {
                key: building.get(key)
                for key in ("id", "entrance_node_id", "position", "footprint", "rings")
            }
            for building in scenario.get("buildings", [])
        ],
    }
    return hashlib.sha256(
        json.dumps(
            content, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def initialize_population_state(simulation) -> None:
    simulation.world_identity = world_identity(simulation.scenario)
    simulation.roster_revision = 0
    simulation.next_resident_identity = max(
        (
            int(identity[len(LIVE_PREFIX) :])
            for identity in simulation._sources
            if identity.startswith(LIVE_PREFIX)
            and identity[len(LIVE_PREFIX) :].isdigit()
        ),
        default=0,
    )
    simulation.joined_at = {}
    simulation.population_change = None


def frozen_population_view(simulation):
    """Capture mutable domain records on the owner loop, sharing immutable graph data."""
    frozen = copy.copy(simulation)
    frozen.graph = copy.copy(simulation.graph)
    frozen.graph._cache = simulation.graph._cache.copy()
    frozen.graph._native_routes = None
    frozen._residents = {}
    for identity, resident in simulation._residents.items():
        item = copy.copy(resident)
        item.trip = copy.copy(resident.trip) if resident.trip is not None else None
        frozen._residents[identity] = item
    frozen._active_trips = {
        item.trip.id: item.trip
        for item in frozen._residents.values()
        if item.trip is not None
    }
    frozen._sources = simulation._sources.copy()
    frozen._queue = list(simulation._queue)
    frozen._occupants = {
        key: set(value) for key, value in simulation._occupants.items()
    }
    frozen._events = deque(simulation._events, maxlen=256)
    frozen._recurring_ids = set(simulation._recurring_ids)
    frozen.joined_at = dict(simulation.joined_at)
    return frozen


def prepare_population_delta(simulation, target: int) -> PopulationDelta:
    """Run on a detached view; generate only added metadata, never a replacement day."""
    target = validate_population(target)
    current = len(simulation._sources)
    removals = ()
    additions = []
    next_identity = simulation.next_resident_identity
    if target < current:
        ordered = sorted(
            simulation._sources,
            key=lambda key: (
                int(simulation._sources[key].get("live_added_ordinal", 0)),
                key,
            ),
            reverse=True,
        )
        removals = tuple(ordered[: current - target])
    elif target > current:
        donors = sorted(simulation._sources)
        if not donors:
            raise ValueError("Live population needs at least one existing assignment")
        for _ in range(target - current):
            next_identity += 1
            if next_identity >= (1 << 53):
                raise ValueError(
                    "Resident identity allocator exhausted its JSON-safe range"
                )
            identity = f"{LIVE_PREFIX}{next_identity:012d}"
            rng = random.Random(f"{simulation.scenario.get('seed', 7)}:{identity}")
            source = copy.deepcopy(
                simulation._sources[donors[rng.randrange(len(donors))]]
            )
            source.update(
                id=identity,
                label=f"Added resident {next_identity}",
                live_added_ordinal=next_identity,
                allocation_source="Synthetic live experiment; reuses an existing home/work pair and schedule",
            )
            source["phase"] = rng.random() * 6.283185307179586
            if "color" in source:
                source["color"] = [
                    round(rng.uniform(0.15, 0.9), 4) for _ in source["color"]
                ]
            additions.append(source)
            # Warm both immutable routes in the detached graph cache before commit.
            for origin, destination in (
                (source["home_id"], source["work_id"]),
                (source["work_id"], source["home_id"]),
            ):
                simulation.graph.route(
                    simulation._buildings[origin]["entrance_node_id"],
                    simulation._buildings[destination]["entrance_node_id"],
                )
    return PopulationDelta(
        simulation.roster_revision, target, tuple(additions), removals, next_identity
    )


def seek_current_schedule(simulation, tick: int) -> None:
    """Initialize current schedule phases in at most one commute cycle per resident.

    Used only on a detached new cohort or a restoring model. It does not replay
    earlier days or publish inferred historical events.
    """
    from .model import Resident

    simulation.tick = 0
    simulation._residents = {}
    simulation._occupants = {key: set() for key in simulation._buildings}
    simulation._active_trips = {}
    simulation._queue = []
    simulation._events = deque(maxlen=256)
    simulation._event_count = 0
    for identity, source in sorted(simulation._sources.items()):
        cycle = 0
        if identity in simulation._recurring_ids and tick >= source["departure_tick"]:
            cycle = (tick - source["departure_tick"]) // simulation._repeat_period
        item = Resident(source, "home", source["home_id"], cycle_index=cycle)
        if cycle:
            home = simulation._buildings[source["home_id"]]["entrance_node_id"]
            work = simulation._buildings[source["work_id"]]["entrance_node_id"]
            route = simulation.graph.route(work, home)
            item.heading = route.sample(route.length).heading
        simulation._residents[identity] = item
        simulation._occupants[source["home_id"]].add(identity)
        simulation._schedule(
            source["departure_tick"] + cycle * simulation._repeat_period,
            identity,
            "depart_outbound",
        )
    simulation._process_events_to(tick)


def preview_population(simulation, delta: PopulationDelta):
    """Build a reversible candidate at the current completed tick, retaining survivors."""
    from .model import CivicSimulation, _RecordTemplate

    if simulation.roster_revision != delta.expected_revision:
        raise ValueError("Population preparation has a stale roster revision")
    if delta.target == len(simulation._sources):
        return simulation
    removed = set(delta.removals)
    if not removed <= simulation._sources.keys():
        raise ValueError("Population removal includes an unknown identity")
    addition_ids = {source["id"] for source in delta.additions}
    if (
        len(addition_ids) != len(delta.additions)
        or addition_ids & simulation._sources.keys()
    ):
        raise ValueError("Population additions contain duplicate identities")
    candidate = copy.copy(simulation)
    candidate._sources = {
        key: value for key, value in simulation._sources.items() if key not in removed
    }
    candidate._sources.update((source["id"], source) for source in delta.additions)
    if len(candidate._sources) != delta.target:
        raise ValueError("Prepared population does not match target")
    candidate._residents = {
        key: value for key, value in simulation._residents.items() if key not in removed
    }
    candidate._resident_templates = {
        key: value
        for key, value in simulation._resident_templates.items()
        if key not in removed
    }
    candidate._resident_templates.update(
        (source["id"], _RecordTemplate(source)) for source in delta.additions
    )
    candidate._occupants = {
        key: values - removed for key, values in simulation._occupants.items()
    }
    candidate._queue = [event for event in simulation._queue if event[2] not in removed]
    candidate._active_trips = {
        resident.trip.id: resident.trip
        for resident in candidate._residents.values()
        if resident.trip is not None
    }
    candidate._recurring_ids = simulation._recurring_ids - removed
    candidate._events = deque(simulation._events, maxlen=256)
    candidate.joined_at = {
        key: value for key, value in simulation.joined_at.items() if key not in removed
    }
    if delta.additions:
        # A small detached cohort shares the prepared graph. Its private historical
        # events are discarded; only present state and future transitions are merged.
        cohort = CivicSimulation.__new__(CivicSimulation)
        cohort.scenario = simulation.scenario
        cohort.graph = simulation.graph
        cohort._buildings = simulation._buildings
        cohort._sources = {source["id"]: source for source in delta.additions}
        cohort._repeat_period = simulation._repeat_period
        cohort.tick_hz = simulation.tick_hz
        cohort._recurring_ids = set()
        if cohort._repeat_period:
            cohort._validate_daily_cycles()
        cohort.paused = simulation.paused
        cohort.speed = simulation.speed
        seek_current_schedule(cohort, simulation.tick)
        candidate._residents.update(cohort._residents)
        candidate._active_trips.update(cohort._active_trips)
        candidate._recurring_ids.update(cohort._recurring_ids)
        candidate._queue.extend(cohort._queue)
        for key, values in cohort._occupants.items():
            candidate._occupants[key].update(values)
        candidate.joined_at.update(
            (identity, simulation.tick) for identity in cohort._residents
        )
    heapq.heapify(candidate._queue)
    candidate.roster_revision = simulation.roster_revision + 1
    candidate.next_resident_identity = delta.next_identity
    candidate.scenario = dict(simulation.scenario)
    candidate.scenario.pop("sha256", None)
    candidate.scenario["residents"] = list(candidate._sources.values())
    candidate.scenario["population"] = delta.target
    candidate.scenario["roster_revision"] = candidate.roster_revision
    candidate.scenario["world_identity"] = simulation.world_identity
    homes = Counter(source["home_id"] for source in candidate._sources.values())
    works = Counter(source["work_id"] for source in candidate._sources.values())
    assigned = Counter()
    for source in candidate._sources.values():
        assigned.update({source["home_id"], source["work_id"]})
    buildings = []
    for original in simulation.scenario["buildings"]:
        building = dict(original)
        identity = building["id"]
        building["generated_home_resident_count"] = homes[identity]
        building["generated_work_resident_count"] = works[identity]
        if "synthetic" in str(
            building.get("capacity_source", "")
        ) or not simulation.scenario.get("geography_manifest"):
            building["capacity"] = assigned[identity]
            building["capacity_source"] = (
                "Synthetic live cohort assignments; not observed building capacity"
            )
        buildings.append(building)
    candidate.scenario["buildings"] = buildings
    candidate._buildings = {building["id"]: building for building in buildings}
    candidate._building_templates = {
        key: _RecordTemplate(value)
        for key, value in sorted(candidate._buildings.items())
    }
    for identity in delta.removals:
        candidate._event(
            "resident_removed", identity, roster_revision=candidate.roster_revision
        )
    for source in delta.additions:
        candidate._event(
            "resident_added", source["id"], roster_revision=candidate.roster_revision
        )
    return candidate


def commit_population(simulation, candidate) -> None:
    """Install a fully validated current-tick candidate; callers own the model loop."""
    if candidate is simulation:
        return
    if (
        candidate.tick != simulation.tick
        or candidate.roster_revision != simulation.roster_revision + 1
    ):
        raise ValueError("Live population candidate is no longer current")
    simulation.__dict__.update(candidate.__dict__)


def capture_runtime(simulation) -> dict:
    residents = []
    for identity, resident in simulation._residents.items():
        trip = resident.trip
        residents.append(
            {
                "id": identity,
                "activity": resident.activity,
                "building_id": resident.building_id,
                "heading": resident.heading,
                "blocked_reason": resident.blocked_reason,
                "cycle_index": resident.cycle_index,
                "trip": (
                    None
                    if trip is None
                    else {
                        "id": trip.id,
                        "departure_tick": trip.departure_tick,
                        "arrival_tick": trip.arrival_tick,
                        "origin_id": trip.origin_id,
                        "destination_id": trip.destination_id,
                        "direction": trip.direction,
                    }
                ),
            }
        )
    return {
        "roster_revision": simulation.roster_revision,
        "next_resident_identity": simulation.next_resident_identity,
        "joined_at": dict(simulation.joined_at),
        "residents": residents,
        "queue": [list(event) for event in sorted(simulation._queue)],
    }


def restore_runtime(simulation, runtime: dict, state: dict) -> None:
    """Restore data records, checking schedules/occupancy against canonical current state."""
    import json

    from .model import _RecordTemplate

    expected = {
        "roster_revision",
        "next_resident_identity",
        "joined_at",
        "residents",
        "queue",
    }
    if type(runtime) is not dict or set(runtime) != expected:
        raise ValueError("Live checkpoint runtime has invalid fields")
    for key in ("roster_revision", "next_resident_identity"):
        if type(runtime[key]) is not int or not 0 <= runtime[key] < (1 << 53):
            raise ValueError(f"Live checkpoint {key} is invalid")
    if runtime["roster_revision"] < 1 or runtime[
        "roster_revision"
    ] != simulation.scenario.get("roster_revision"):
        raise ValueError("Live checkpoint roster revision mismatch")
    if type(runtime["joined_at"]) is not dict:
        raise ValueError("Live checkpoint joined_at must be an object")
    ordinals = [
        source.get("live_added_ordinal", 0) for source in simulation._sources.values()
    ]
    if any(type(value) is not int or not 0 <= value < (1 << 53) for value in ordinals):
        raise ValueError("Live checkpoint insertion ordinal is invalid")
    max_ordinal = max(ordinals, default=0)
    if runtime["next_resident_identity"] < max(
        max_ordinal, simulation.next_resident_identity
    ):
        raise ValueError("Live checkpoint allocator would reuse an identity")
    added = {
        key
        for key, source in simulation._sources.items()
        if source.get("live_added_ordinal", 0)
    }
    if set(runtime["joined_at"]) != added:
        raise ValueError("Live checkpoint insertion metadata does not match roster")
    if any(
        type(tick) is not int or not 0 <= tick <= state["tick"]
        for tick in runtime["joined_at"].values()
    ):
        raise ValueError("Live checkpoint insertion tick is invalid")
    # Schedules remain deterministic after additions: validate current domain state
    # independently, then restore the authoritative bounded history, not past births.
    seek_current_schedule(simulation, state["tick"])
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    generated = capture_runtime(simulation)
    if type(runtime["residents"]) is not list or any(
        type(row) is not dict or type(row.get("id")) is not str
        for row in runtime["residents"]
    ):
        raise ValueError("Live checkpoint resident records are invalid")
    records = {row["id"]: row for row in runtime["residents"]}
    expected_records = {row["id"]: row for row in generated["residents"]}
    if (
        len(records) != len(runtime["residents"])
        or canonical(records) != canonical(expected_records)
        or canonical(runtime["queue"]) != canonical(generated["queue"])
    ):
        raise ValueError("Live checkpoint runtime does not match current schedules")
    simulation._residents = {
        row["id"]: simulation._residents[row["id"]] for row in runtime["residents"]
    }
    if type(state["event_count"]) is not int or state["event_count"] < len(
        state["events"]
    ):
        raise ValueError("Live checkpoint event count is invalid")
    last_sequence = 0
    last_tick = -1
    for event in state["events"]:
        if (
            type(event.get("sequence")) is not int
            or not last_sequence < event["sequence"] <= state["event_count"]
        ):
            raise ValueError("Live checkpoint event ordering is invalid")
        if (
            type(event.get("tick")) is not int
            or not last_tick <= event["tick"] <= state["tick"]
        ):
            raise ValueError("Live checkpoint event tick is invalid")
        if event.get("type") not in {
            "departure",
            "arrival",
            "blocked",
            "resident_added",
            "resident_removed",
        }:
            raise ValueError("Live checkpoint event kind is invalid")
        if type(event.get("resident_id")) is not str or not event["resident_id"]:
            raise ValueError("Live checkpoint event resident is invalid")
        last_sequence, last_tick = event["sequence"], event["tick"]
    if state["events"] and last_sequence != state["event_count"]:
        raise ValueError("Live checkpoint history does not end at event count")
    simulation._events = deque(
        (_RecordTemplate(event) for event in state["events"]), maxlen=256
    )
    simulation._event_count = state["event_count"]
    simulation.roster_revision = runtime["roster_revision"]
    simulation.next_resident_identity = runtime["next_resident_identity"]
    simulation.joined_at = dict(runtime["joined_at"])
    simulation.set_paused(state["paused"])
    simulation.set_speed(state["speed"])
    if canonical(
        simulation.snapshot(include_static=False, include_trip_geometry=False)
    ) != canonical(state):
        raise ValueError("Live checkpoint occupancy or resident state is inconsistent")
