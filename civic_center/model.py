"""Persistent residents and exact-tick commute events for the City Hall pilot.

Clock advancement visits departures and arrivals, rather than iterating every
resident at 200 Hz. Positions are sampled from complete cached routes at the
requested completed tick. Rendering, playback speed and advancement batch size
therefore cannot change a person's authoritative journey.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from typing import Any, Iterable

from .routing import WalkingGraph, WalkingRoute, _identifier

_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))
DAILY_SCHEDULE_MODE = "daily-v1"
DAY_SECONDS = 86_400
MAX_REPEAT_TICK = (1 << 53) - 1


class _RecordTemplate:
    """Prepare cheap detached copies of metadata that does not change in a day.

    Most resident metadata is scalar values plus four short color lists. Generic
    deepcopy repeatedly builds memo tables and visits every scalar; this template
    copies the dictionary and those known flat lists directly. Unusual nested
    metadata retains deepcopy semantics. The private template owns its input so
    neither the caller's scenario nor a returned snapshot can change its shape.
    """

    __slots__ = ("_values", "_copy_fields")

    def __init__(self, record: dict[str, Any]) -> None:
        self._values = record.copy()
        self._copy_fields = []
        for name, value in self._values.items():
            if type(value) in _JSON_SCALAR_TYPES:
                continue
            if type(value) is list and all(
                type(item) in _JSON_SCALAR_TYPES for item in value
            ):
                value = value.copy()
                copier = value.copy
            else:
                value = deepcopy(value)
                # A module-level callable also lets the worker transfer a
                # validated model over its private child-process IPC channel.
                copier = partial(deepcopy, value)
            self._values[name] = value
            self._copy_fields.append((name, copier))

    def copy(self) -> dict[str, Any]:
        record = self._values.copy()
        for name, copier in self._copy_fields:
            record[name] = copier()
        return record


def _tick_count(value: Any, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{description} must be a nonnegative integer")
    return value


def _positive_number(value: Any, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{description} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{description} must be a finite positive number")
    return result


@dataclass
class Trip:
    id: str
    route: WalkingRoute
    departure_tick: int
    arrival_tick: int
    origin_id: str
    destination_id: str
    direction: str


@dataclass
class Resident:
    source: dict[str, Any]
    activity: str
    building_id: str | None
    trip: Trip | None = None
    blocked_reason: str | None = None
    heading: float = 0.0
    cycle_index: int = 0


class CivicSimulation:
    """Simulate scheduled home/work/home journeys while preserving identities.

    ``advance_ticks`` respects pause. ``step_ticks`` deliberately advances even
    while paused for headless replay and single-step controls. Neither multiplies
    by playback speed; the real-time adapter owns that conversion. Reset restores
    the initial scenario, including tick zero, unpaused state and speed 1.

    ``routing_backend`` optionally selects auto/python/rust without changing the
    scenario or snapshot schema; omitted selection follows the router environment.

    Capacity is descriptive in this first scenario: no admission, household or
    workplace allocation policy is inferred. The journal contains the latest 256
    events, and ``event_count`` counts all events since reset.

    Resident ``moving`` means an active walking activity, including when paused;
    top-level pause freezes the simulation clock and the viewer's existing gait
    pose rather than changing that person to a standing pose.

    An explicit ``schedule: {mode: daily-v1}`` repeats each person's schedule
    every 86,400 seconds. Reachable round trips must finish by the next departure;
    immutable disconnected routes remain blocked. Ticks in this mode retain two
    periods of headroom below the JSON-safe maximum for future trip timestamps.
    Long jumps skip complete periodic cycles and
    rebuild only the final journal, so work does not grow with elapsed days.
    """

    def __init__(
        self, scenario: dict[str, Any], *, routing_backend: str | None = None
    ) -> None:
        if not isinstance(scenario, dict) or scenario.get("schema_version") != 1:
            raise ValueError("scenario schema_version must be 1")
        self.scenario = deepcopy(scenario)
        self.tick_hz = _tick_count(scenario.get("tick_hz"), "tick_hz")
        if self.tick_hz == 0:
            raise ValueError("tick_hz must be positive")
        self._repeat_period = 0
        if "schedule" in scenario:
            schedule = scenario["schedule"]
            if (
                type(schedule) is not dict
                or set(schedule) != {"mode"}
                or schedule["mode"] != DAILY_SCHEDULE_MODE
            ):
                raise ValueError("schedule must be {mode: daily-v1} when supplied")
            self._repeat_period = DAY_SECONDS * self.tick_hz
            if self._repeat_period > MAX_REPEAT_TICK // 3:
                raise ValueError(
                    "daily schedule period exceeds the JSON-safe tick range"
                )
        self.start_time_seconds = scenario.get("start_time_seconds", 0.0)
        if (
            isinstance(self.start_time_seconds, bool)
            or not isinstance(self.start_time_seconds, (float, int))
            or not math.isfinite(self.start_time_seconds)
        ):
            raise ValueError("start_time_seconds must be finite")
        self.graph = WalkingGraph(
            scenario.get("nodes", []),
            scenario.get("edges", []),
            backend=routing_backend,
        )
        self._buildings: dict[str, dict[str, Any]] = {}
        for building in self.scenario.get("buildings", []):
            building_id = _identifier(building.get("id"), "building id")
            if building_id in self._buildings:
                raise ValueError(f"duplicate building id: {building_id}")
            if building.get("entrance_node_id") not in self.graph.positions:
                raise ValueError(f"building {building_id} has an unknown entrance")
            if "capacity" in building:
                _tick_count(building["capacity"], f"building {building_id} capacity")
            self._buildings[building_id] = building
        self._sources: dict[str, dict[str, Any]] = {}
        for source in self.scenario.get("residents", []):
            resident_id = _identifier(source.get("id"), "resident id")
            if resident_id in self._sources:
                raise ValueError(f"duplicate resident id: {resident_id}")
            for assignment in ("home_id", "work_id"):
                if source.get(assignment) not in self._buildings:
                    raise ValueError(
                        f"resident {resident_id} has an unknown {assignment}"
                    )
            departure = _tick_count(source.get("departure_tick"), "departure_tick")
            return_tick = _tick_count(source.get("return_tick"), "return_tick")
            if return_tick < departure:
                raise ValueError(f"resident {resident_id} returns before departure")
            _positive_number(source.get("speed_mps"), "resident speed_mps")
            self._sources[resident_id] = source
        self._recurring_ids: set[str] = set()
        if self._repeat_period:
            self._validate_daily_cycles()
        self._resident_templates = {
            resident_id: _RecordTemplate(source)
            for resident_id, source in self._sources.items()
        }
        self._building_templates = {
            building_id: _RecordTemplate(source)
            for building_id, source in sorted(self._buildings.items())
        }
        self.reset()
        from .population import initialize_population_state

        initialize_population_state(self)

    @staticmethod
    def _travel_ticks(route: WalkingRoute, source: dict[str, Any], tick_hz: int) -> int:
        # Ceiling prevents early arrivals; nextafter removes a one-ULP upward
        # arithmetic error at an otherwise exact integer duration.
        duration = route.length / source["speed_mps"] * tick_hz
        if not math.isfinite(duration):
            raise ValueError("walking trip duration must be finite")
        return max(0, math.ceil(math.nextafter(duration, -math.inf)))

    def _validate_daily_cycles(self) -> None:
        """Establish the periodic regime before allowing analytical day skips."""
        for resident_id, source in self._sources.items():
            departure, return_tick = source["departure_tick"], source["return_tick"]
            deadline = departure + self._repeat_period
            if departure >= self._repeat_period or return_tick > deadline:
                raise ValueError(
                    f"resident {resident_id} daily schedule exceeds its next departure"
                )
            home = self._buildings[source["home_id"]]["entrance_node_id"]
            work = self._buildings[source["work_id"]]["entrance_node_id"]
            outbound = self.graph.route(home, work)
            if outbound is None:
                continue
            outbound_arrival = departure + self._travel_ticks(
                outbound, source, self.tick_hz
            )
            return_departure = max(outbound_arrival, return_tick)
            if return_departure > deadline:
                raise ValueError(
                    f"resident {resident_id} outbound trip overlaps its next daily departure"
                )
            inbound = self.graph.route(work, home)
            if inbound is None:
                continue
            home_arrival = return_departure + self._travel_ticks(
                inbound, source, self.tick_hz
            )
            if home_arrival > deadline:
                raise ValueError(
                    f"resident {resident_id} round trip overlaps its next daily departure"
                )
            self._recurring_ids.add(resident_id)

    def reset(self) -> None:
        if hasattr(self, "joined_at"):
            self.joined_at = dict.fromkeys(self.joined_at, 0)
            self.population_change = None
        self.tick = 0
        self.paused = False
        self.speed = 1.0
        self._residents: dict[str, Resident] = {}
        self._occupants: dict[str, set[str]] = {
            building_id: set() for building_id in self._buildings
        }
        self._queue: list[tuple[int, int, str, str]] = []
        self._active_trips: dict[str, Trip] = {}
        self._events: deque[_RecordTemplate] = deque(maxlen=256)
        self._event_count = 0
        for resident_id, source in sorted(self._sources.items()):
            self._residents[resident_id] = Resident(source, "home", source["home_id"])
            self._occupants[source["home_id"]].add(resident_id)
            self._schedule(source["departure_tick"], resident_id, "depart_outbound")
        self._advance_to(0)

    def set_paused(self, paused: bool) -> None:
        if not isinstance(paused, bool):
            raise ValueError("paused must be a boolean")
        self.paused = paused

    def set_speed(self, speed: float) -> None:
        self.speed = _positive_number(speed, "playback speed")

    def advance_ticks(self, count: int) -> int:
        """Advance exactly count completed ticks unless paused; return new tick."""
        count = _tick_count(count, "tick count")
        if not self.paused:
            self._advance_to(self.tick + count)
        return self.tick

    def step_ticks(self, count: int = 1) -> int:
        """Explicit deterministic advancement that also works while paused."""
        count = _tick_count(count, "tick count")
        self._advance_to(self.tick + count)
        return self.tick

    def next_event_tick(self) -> int | None:
        """Return the next activity tick, or None when no transitions remain."""
        return self._queue[0][0] if self._queue else None

    def _schedule(self, tick: int, resident_id: str, kind: str) -> None:
        priority = 0 if kind == "arrive" else 1
        heapq.heappush(self._queue, (tick, priority, resident_id, kind))

    def _advance_to(self, target_tick: int) -> None:
        if self._repeat_period:
            if target_tick > MAX_REPEAT_TICK - 2 * self._repeat_period:
                raise ValueError(
                    "repeating schedule target exceeds the JSON-safe tick range"
                )
            # Every initial trip or immutable blockage is resolved by two
            # periods. Thereafter state repeats exactly up to time/trip IDs.
            if target_tick - self.tick > self._repeat_period:
                warm_end = min(target_tick, 2 * self._repeat_period)
                if self.tick < warm_end:
                    self._process_events_to(warm_end)
                events_per_period = 4 * len(self._recurring_ids)
                if events_per_period:
                    journal_periods = max(1, math.ceil(256 / events_per_period))
                    complete_periods = (target_tick - self.tick) // self._repeat_period
                    skipped = max(0, complete_periods - journal_periods)
                    if skipped:
                        self._skip_daily_periods(skipped, events_per_period)
        self._process_events_to(target_tick)

    def _skip_daily_periods(self, count: int, events_per_period: int) -> None:
        shift = count * self._repeat_period
        self.tick += shift
        self._queue = [
            (tick + shift, priority, identity, kind)
            for tick, priority, identity, kind in self._queue
        ]
        self._active_trips.clear()
        for resident_id in self._recurring_ids:
            resident = self._residents[resident_id]
            resident.cycle_index += count
            if resident.trip is not None:
                trip = resident.trip
                trip.id = f"{resident_id}:{trip.direction}:{resident.cycle_index}"
                trip.departure_tick += shift
                trip.arrival_tick += shift
                self._active_trips[trip.id] = trip
        self._event_count += count * events_per_period
        # The caller processes enough final periods to replace the entire
        # journal with real ordered transitions and exact sequence numbers.
        self._events.clear()

    def _process_events_to(self, target_tick: int) -> None:
        while self._queue and self._queue[0][0] <= target_tick:
            tick, _priority, resident_id, kind = heapq.heappop(self._queue)
            self.tick = tick
            resident = self._residents[resident_id]
            if kind == "arrive":
                self._arrive(resident_id, resident)
            else:
                self._depart(resident_id, resident, kind == "depart_outbound")
        self.tick = target_tick

    def _event(self, kind: str, resident_id: str, **fields: Any) -> None:
        self._event_count += 1
        self._events.append(
            _RecordTemplate(
                {
                    "sequence": self._event_count,
                    "type": kind,
                    "tick": self.tick,
                    "resident_id": resident_id,
                    **fields,
                }
            )
        )

    def _depart(self, resident_id: str, resident: Resident, outbound: bool) -> None:
        source = resident.source
        if outbound and self._repeat_period:
            resident.cycle_index = (
                self.tick - source["departure_tick"]
            ) // self._repeat_period
        origin = source["home_id"] if outbound else source["work_id"]
        destination = source["work_id"] if outbound else source["home_id"]
        route = self.graph.route(
            self._buildings[origin]["entrance_node_id"],
            self._buildings[destination]["entrance_node_id"],
        )
        direction = "outbound" if outbound else "return"
        trip_id = f"{resident_id}:{direction}:{resident.cycle_index}"
        if route is None:
            resident.activity = "blocked"
            resident.blocked_reason = f"No walking route from {origin} to {destination}"
            self._event(
                "blocked",
                resident_id,
                trip_id=trip_id,
                building_id=origin,
                destination_id=destination,
                reason=resident.blocked_reason,
            )
            return
        travel_ticks = self._travel_ticks(route, source, self.tick_hz)
        resident.trip = Trip(
            trip_id,
            route,
            self.tick,
            self.tick + travel_ticks,
            origin,
            destination,
            direction,
        )
        self._active_trips[trip_id] = resident.trip
        resident.activity = "walking_to_work" if outbound else "walking_home"
        resident.blocked_reason = None
        resident.building_id = None
        resident.heading = route.sample(0.0).heading
        self._occupants[origin].remove(resident_id)
        self._event(
            "departure",
            resident_id,
            trip_id=trip_id,
            building_id=origin,
            destination_id=destination,
        )
        self._schedule(resident.trip.arrival_tick, resident_id, "arrive")

    def _arrive(self, resident_id: str, resident: Resident) -> None:
        trip = resident.trip
        assert trip is not None
        resident.heading = trip.route.sample(trip.route.length).heading
        resident.building_id = trip.destination_id
        resident.activity = "at_work" if trip.direction == "outbound" else "home"
        del self._active_trips[trip.id]
        resident.trip = None
        self._occupants[trip.destination_id].add(resident_id)
        self._event(
            "arrival",
            resident_id,
            trip_id=trip.id,
            building_id=trip.destination_id,
        )
        if trip.direction == "outbound":
            self._schedule(
                max(
                    self.tick,
                    resident.source["return_tick"]
                    + resident.cycle_index * self._repeat_period,
                ),
                resident_id,
                "depart_return",
            )
        elif self._repeat_period:
            self._schedule(
                resident.source["departure_tick"]
                + (resident.cycle_index + 1) * self._repeat_period,
                resident_id,
                "depart_outbound",
            )

    def active_trip_ids(self) -> tuple[str, ...]:
        """Capture current trip identities on the owner loop without a snapshot."""
        return tuple(self._active_trips)

    def trip_geometries(self, trip_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Return detached definitions for active requested trips, once per ID.

        A negotiated transport can send these definitions reliably before compact
        references. Unknown/inactive IDs are rejected rather than returning a
        partial batch. Trip lookup neither advances the clock nor mutates routes.
        """
        return [
            dict(
                record,
                points=[list(point) for point in record["points"]],
                node_ids=list(record["node_ids"]),
            )
            for record in self.capture_trip_geometries(trip_ids)
        ]

    def capture_trip_geometries(self, trip_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Capture active geometry without copying its immutable coordinate arrays.

        Call on the model's owner loop. Returned dictionaries are detached; their
        points and node IDs retain frozen route tuples. A background encoder can
        consume them after advancement, arrival, reset or model replacement,
        without touching the live model. JSON encoding matches trip_geometries.
        """
        if isinstance(trip_ids, (str, bytes)):
            raise ValueError("trip_ids must be an iterable of active trip ID strings")
        requested = list(trip_ids)
        if any(type(identity) is not str or not identity for identity in requested):
            raise ValueError("trip_ids must contain nonempty strings")
        requested = list(dict.fromkeys(requested))
        unknown = [
            identity for identity in requested if identity not in self._active_trips
        ]
        if unknown:
            raise ValueError(f"Unknown or inactive trip ID: {unknown[0]}")
        return [
            {
                "id": identity,
                "points": self._active_trips[identity].route.points,
                "node_ids": self._active_trips[identity].route.node_ids,
                "length_m": self._active_trips[identity].route.length,
            }
            for identity in requested
        ]

    def snapshot(
        self,
        *,
        include_static: bool = True,
        include_trip_geometry: bool = True,
    ) -> dict[str, Any]:
        """Return detached state, optionally excluding immutable source metadata.

        The default is the complete checkpoint/replay representation. A transport
        that already supplied scenario resident/building records may request only
        their IDs and dynamic fields, then merge those fields by stable ID before
        presenting them. A separately negotiated geometry dictionary can also omit
        immutable trip geometry. Segment indices address route.points, while
        trip.node_ids names the (potentially sparser) routing graph junctions.
        """
        if type(include_static) is not bool:
            raise ValueError("include_static must be a boolean")
        if type(include_trip_geometry) is not bool:
            raise ValueError("include_trip_geometry must be a boolean")
        residents = []
        # reset inserts these records in stable ID order; visibility and render
        # slots never change their membership or insertion order.
        for resident_id, resident in self._residents.items():
            record = (
                self._resident_templates[resident_id].copy()
                if include_static
                else {"id": resident_id}
            )
            trip = resident.trip
            heading = resident.heading
            if trip is None:
                assert resident.building_id is not None
                node_id = self._buildings[resident.building_id]["entrance_node_id"]
                position = self.graph.positions[node_id]
                trip_record = None
            else:
                distance = (
                    (self.tick - trip.departure_tick)
                    / self.tick_hz
                    * resident.source["speed_mps"]
                )
                sample = trip.route.sample(distance)
                position, heading = sample.position, sample.heading
                trip_record = {"id": trip.id}
                if include_trip_geometry:
                    trip_record.update(
                        points=[list(point) for point in trip.route.points],
                        node_ids=list(trip.route.node_ids),
                        length_m=trip.route.length,
                    )
                trip_record.update(
                    {
                        "segment_index": sample.segment_index,
                        "segment_progress": sample.segment_progress,
                        "departure_tick": trip.departure_tick,
                        "arrival_tick": trip.arrival_tick,
                        "origin_id": trip.origin_id,
                        "destination_id": trip.destination_id,
                    }
                )
            record.update(
                activity=resident.activity,
                building_id=resident.building_id,
                position=list(position),
                heading=heading,
                visible=trip is not None,
                moving=trip is not None,
                trip=trip_record,
                blocked_reason=resident.blocked_reason,
            )
            residents.append(record)
        buildings = []
        for building_id, template in self._building_templates.items():
            record = template.copy() if include_static else {"id": building_id}
            record.update(
                occupancy=len(self._occupants[building_id]),
                resident_ids=sorted(self._occupants[building_id]),
            )
            buildings.append(record)
        result = {
            "tick": self.tick,
            "simulation_time": self.tick / self.tick_hz,
            "clock_seconds": self.start_time_seconds + self.tick / self.tick_hz,
            "paused": self.paused,
            "speed": self.speed,
            "residents": residents,
            "buildings": buildings,
            "events": [event.copy() for event in self._events],
            "event_count": self._event_count,
        }
        if self._repeat_period:
            clock_seconds = result["clock_seconds"]
            result["day_index"] = math.floor(clock_seconds / DAY_SECONDS)
            result["day_seconds"] = clock_seconds % DAY_SECONDS
        return result
