"""Deterministic, explicitly synthetic walking scenario for the City Hall pilot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import random
from typing import Any

POPULATIONS = (1, 20, 200, 1000, 5000)
TICK_HZ = 200
START_SECONDS = 7 * 3600 + 59 * 60 + 50
DATA_ROOT = Path(__file__).resolve().parent / "data"

_CLOTHES = [[.88, .48, .17], [.12, .43, .46], [.65, .22, .17], [.35, .32, .55]]
_SKINS = [[.63, .39, .25], [.87, .67, .49], [.38, .23, .16], [.74, .51, .34]]


def scenario_hash(scenario: dict[str, Any]) -> str:
    """Content identity excludes its own checksum field."""
    payload = {key: value for key, value in scenario.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def make_scenario(population: int = 200, seed: int = 7, *, repeat_days: bool = False) -> dict[str, Any]:
    if type(population) is not int or population not in POPULATIONS:
        raise ValueError(f"Population must be one of {POPULATIONS}")
    if type(seed) is not int:
        raise ValueError("Seed must be an integer")
    if type(repeat_days) is not bool:
        raise ValueError("repeat_days must be a boolean")
    rng = random.Random(seed)
    nodes: dict[str, list[float]] = {}
    edges: list[dict[str, Any]] = []

    def node(identity: str, x: float, y: float, z: float | None = None) -> str:
        if z is None:
            # The source asset's central block top is .33 m; the exterior road
            # baseline is .08 m. A centimetre of foot clearance avoids z-fighting.
            z = .34 if -72 <= x <= 72 and -72 <= y <= 82 else .08
        nodes[identity] = [x, y, z]
        return identity

    def connect(*identities: str) -> None:
        for first, second in zip(identities, identities[1:]):
            edges.append({"id": f"edge:{first}:{second}", "from": first, "to": second,
                          "bidirectional": True})

    for identity, x, y in [
        ("sw", -66, -66), ("se", 66, -66), ("west", -66, 0),
        ("east", 66, 0), ("east_mid", 66, 25), ("nw", -66, 77),
        ("ne", 66, 77), ("north_w", -66, 108), ("north_e", 66, 108),
        ("south_w", -66, -104), ("south_e", 66, -104),
    ]:
        node(identity, x, y)
    connect("sw", "west", "nw", "ne", "east_mid", "east", "se", "sw")
    for side, x in [("w", -66), ("e", 66)]:
        node(f"north_{side}_curb", x, 82, .34)
        node(f"north_{side}_ramp", x, 83, .08)
        node(f"south_{side}_curb", x, -72, .34)
        node(f"south_{side}_ramp", x, -73, .08)
        connect(f"n{side}", f"north_{side}_curb", f"north_{side}_ramp", f"north_{side}")
        connect(f"s{side}", f"south_{side}_curb", f"south_{side}_ramp", f"south_{side}")
    connect("north_w", "north_e")
    connect("south_w", "south_e")

    # Original block's plaza is raised. These connectors match the visual study,
    # with a ramp approximation over its entrance stair run.
    node("plaza_sw_apron", -57, -62.5, .34)
    node("plaza_se_apron", 57, -62.5, .34)
    node("plaza_sw_edge", -56, -61.5, .48)
    node("plaza_se_edge", 56, -61.5, .48)
    node("plaza_sw", -50, -55, .48)
    node("plaza_se", 50, -55, .48)
    node("plaza_inner_sw", -24, -55, .48)
    node("plaza_inner_se", 24, -55, .48)
    node("plaza_inner_nw", -24, -12, .48)
    node("plaza_inner_ne", 24, -12, .48)
    node("plaza_front", 0, -12, .48)
    node("stair_bottom", 0, -10, .48)
    node("stair_top", 0, 4, 2.4)
    node("entrance:city-hall", 0, 7, 2.4)
    connect("sw", "plaza_sw_apron", "plaza_sw_edge", "plaza_sw", "plaza_inner_sw", "plaza_inner_nw", "plaza_front")
    connect("se", "plaza_se_apron", "plaza_se_edge", "plaza_se", "plaza_inner_se", "plaza_inner_ne", "plaza_front")
    connect("plaza_front", "stair_bottom", "stair_top", "entrance:city-hall")

    buildings: list[dict[str, Any]] = [{
        "id": "city-hall", "label": "City Hall", "kind": "work",
        "entrance_node_id": "entrance:city-hall", "capacity": population,
        "source": "original visual study; generated entrance",
    }]
    specs = [
        (0, "home", "West residences", -113, 0, -103, 0, "west"),
        (1, "work", "East offices", 113, 25, 103, 25, "east_mid"),
        (2, "work", "Northwest offices", -148, 113, -148, 108, "north_w"),
        (3, "home", "North residences", -32, 113, -32, 108, "north_w"),
        (4, "work", "North offices", 48, 113, 48, 108, "north_e"),
        (5, "work", "Northeast offices", 156, 113, 156, 108, "north_e"),
        (6, "home", "Southwest residences", -158, -111, -158, -104, "south_w"),
        (7, "work", "Southwest workshops", -48, -111, -48, -104, "south_w"),
        (8, "work", "South offices", 32, -111, 32, -104, "south_e"),
        (9, "home", "Southeast residences", 154, -111, 154, -104, "south_e"),
    ]
    for index, kind, label, x, y, walk_x, walk_y, anchor in specs:
        identity = f"building-{index}"
        entrance = node(f"entrance:{identity}", x, y)
        connector = node(f"connector:{identity}", walk_x, walk_y)
        if index in (0, 1):
            side = -1 if index == 0 else 1
            outer = node(f"curb-outer:{identity}", side * 73, walk_y, .08)
            inner = node(f"curb-inner:{identity}", side * 72, walk_y, .34)
            connect(entrance, connector, outer, inner, anchor)
        else:
            connect(entrance, connector, anchor)
        buildings.append({"id": identity, "label": label, "kind": kind,
                          "entrance_node_id": entrance, "capacity": population,
                          "source": "original visual study; generated use and entrance"})

    homes = ["building-0", "building-3", "building-6", "building-9"]
    workplaces = ["city-hall", "building-1", "building-2", "building-4",
                  "building-5", "building-7", "building-8"]
    residents = []
    for index in range(population):
        # First person provides a quick, repeatable inspection target; others
        # depart across a twenty-minute window. Workdays are synthetic schedules.
        departure = 10 if index == 0 else 10 + rng.randrange(20 * 60)
        return_seconds = (17 * 3600 - START_SECONDS) + (0 if index == 0 else rng.randrange(30 * 60))
        residents.append({
            "id": f"resident-{index:04d}", "label": f"Resident {index + 1:04d}",
            "home_id": homes[index % len(homes)],
            "work_id": workplaces[index % len(workplaces)],
            "departure_tick": departure * TICK_HZ, "return_tick": return_seconds * TICK_HZ,
            "speed_mps": 1.45 if index == 0 else round(rng.uniform(1.15, 1.65), 3),
            "phase": (index * .61803398875) % 1,
            "color": _CLOTHES[(index // 3 + index) % len(_CLOTHES)].copy(),
            "skin_color": _SKINS[(index // 2) % len(_SKINS)].copy(),
            "trouser_color": [[.08, .12, .18], [.21, .22, .20]][index % 2],
            "bag_color": [[.30, .21, .12], [.15, .18, .20]][index % 2],
        })
    scenario = {
        "schema_version": 1, "id": "civic-center-walking-day-v1",
        "label": "A working day around City Hall", "seed": seed,
        "tick_hz": TICK_HZ, "start_time_seconds": START_SECONDS,
        "population": population, "population_presets": list(POPULATIONS),
        "source_note": "Synthetic schedules, building uses and walking connectors on an original stylized City Hall block. Not surveyed geography or observed residents.",
        "origin": {"longitude": -122.4193, "latitude": 37.7793},
        "coordinate_system": "local east, north, up; meters",
        "nodes": [{"id": identity, "position": position} for identity, position in nodes.items()],
        "edges": edges, "buildings": buildings, "residents": residents,
    }
    if repeat_days:
        scenario["schedule"] = {"mode": "daily-v1"}
    scenario["sha256"] = scenario_hash(scenario)
    return scenario


def load_scenario(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8-sig") as stream:
        scenario = json.load(stream)
    if not isinstance(scenario, dict) or scenario.get("schema_version") != 1:
        raise ValueError("Expected Civic Center scenario schema_version 1")
    if scenario.get("presentation_only"):
        raise ValueError("A viewer presentation projection is not a complete simulation scenario")
    if scenario.get("sha256") and scenario["sha256"] != scenario_hash(scenario):
        raise ValueError("Scenario checksum does not match its contents")
    return scenario


def write_scenario(path: str | Path, population: int = 200, seed: int = 7) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(make_scenario(population, seed), indent=2) + "\n", encoding="utf-8")
