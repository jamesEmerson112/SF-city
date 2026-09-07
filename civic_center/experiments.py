"""Bounded experiment attribution with delayed population commit boundaries."""

from __future__ import annotations

import copy
import math
import time
from collections import deque

MAX_PHASES = 64
MAX_POINTS = 32
MAX_GAUGES = 256


def _add(summary: dict, numbers: dict) -> bool:
    truncated = False
    for key, value in numbers.items():
        if key not in summary:
            if len(summary) >= MAX_GAUGES:
                truncated = True
                continue
            summary[key] = {
                "count": 0,
                "min": value,
                "max": value,
                "mean": 0.0,
                "last": value,
            }
        item = summary[key]
        item["count"] += 1
        item["min"] = min(item["min"], value)
        item["max"] = max(item["max"], value)
        item["mean"] += (value - item["mean"]) / item["count"]
        item["last"] = value
    return truncated


class ExperimentArchive:
    def __init__(
        self,
        started_at_unix: float,
        history_limit: int = 360,
        started_monotonic: float | None = None,
    ):
        self.started_unix = started_at_unix
        self.started = (
            time.monotonic() if started_monotonic is None else started_monotonic
        )
        self._history = deque(maxlen=history_limit)
        self._frozen = {}
        self._oldest_evicted = None
        self._last_sample_at = None
        self._counter = 0
        self.data = {
            "schema_version": 1,
            "phase_limit": MAX_PHASES,
            "phases": [],
            "phases_dropped": 0,
            "unattributed_viewer_reports": 0,
            "comparison_points": [],
            "comparison_points_dropped": 0,
            "measurement": "Hardware interval samples crossing a boundary are mixed "
            "and excluded from phase summaries. Late boundaries are corrected within "
            "retained history; older attribution is explicitly incomplete. Viewer "
            "reports retain their own sample window and percentiles are never averaged.",
        }
        self.phase(
            {
                "reason": "launch",
                "stage": "loading",
                "boundary_at_unix": started_at_unix,
                "boundary_monotonic_seconds": self.started,
                "clock_uncertainty_seconds": 0.0,
            },
            started_at_unix,
            received_monotonic=self.started,
        )

    @property
    def current_id(self):
        return self.data["phases"][-1]["phase_id"]

    def _owner(self, at: float):
        for phase in reversed(self.data["phases"]):
            if phase["boundary_monotonic_seconds"] <= at:
                return phase
        return None

    @staticmethod
    def _empty():
        return {
            "hardware_samples": 0,
            "mixed_samples": 0,
            "hardware_summary": {},
            "summary_truncated": False,
        }

    def _mixed(self, sample):
        if sample["initial"] or not sample["owner"]["attribution_complete"]:
            return True
        for phase in self.data["phases"]:
            boundary = phase["boundary_monotonic_seconds"]
            uncertainty = phase["clock_uncertainty_seconds"]
            if (
                sample["start"] < boundary + uncertainty
                and sample["at"] >= boundary - uncertainty
            ):
                return True
        return False

    def _attribute(self, sample, target):
        target["hardware_samples"] += 1
        if self._mixed(sample):
            target["mixed_samples"] += 1
        else:
            target["summary_truncated"] |= _add(
                target["hardware_summary"], sample["numbers"]
            )

    def sample(
        self,
        at_monotonic: float,
        numbers: dict,
        interval: float,
        context: dict | None = None,
        interval_start: float | None = None,
    ):
        initial = self._last_sample_at is None
        start = self._last_sample_at if not initial else at_monotonic - interval
        if (
            type(interval_start) in (int, float)
            and math.isfinite(interval_start)
            and self.started <= interval_start <= at_monotonic
        ):
            start = interval_start
        self._last_sample_at = at_monotonic
        if len(self._history) == self._history.maxlen:
            old = self._history[0]
            owner = self._owner(old["at"])
            if owner is not None:
                old["owner"] = owner
                frozen = self._frozen.setdefault(owner["phase_id"], self._empty())
                self._attribute(old, frozen)
            self._oldest_evicted = old["at"]
        owner = self._owner(at_monotonic)
        sample = {
            "at": at_monotonic,
            "start": start,
            "numbers": numbers,
            "owner": owner,
            "initial": initial,
            "context": context,
        }
        self._history.append(sample)
        if owner is not None:
            self._attribute(sample, owner)
        attribution = {
            "phase_id": owner["phase_id"] if owner else None,
            "phase_mixed": owner is None or self._mixed(sample),
            "interval_start_monotonic_seconds": start,
            "interval_end_monotonic_seconds": at_monotonic,
        }
        if context is not None:
            context.update(attribution)
        return attribution

    def phase(
        self,
        payload: dict,
        received_at_unix: float,
        received_monotonic: float | None = None,
    ):
        received = (
            time.monotonic() if received_monotonic is None else received_monotonic
        )
        if payload.get("noop") or payload.get("outcome") in {
            "failed",
            "cancelled",
            "rejected",
        }:
            return None
        change = payload.get("population_change")
        change = (
            change
            if isinstance(change, dict) and payload.get("stage") != "settled"
            else {}
        )
        boundary = change.get(
            "committed_monotonic_seconds", payload.get("boundary_monotonic_seconds")
        )
        uncertainty = 0.0 if change else payload.get("clock_uncertainty_seconds")
        valid = (
            type(boundary) in (int, float)
            and math.isfinite(boundary)
            and self.started <= boundary <= received + 1.0
            and type(uncertainty) in (int, float)
            and math.isfinite(uncertainty)
            and 0 <= uncertainty <= 5.0
        )
        if not valid:
            boundary, uncertainty = received, 0.0
        boundary_unix = change.get("committed_at_unix", payload.get("boundary_at_unix"))
        if type(boundary_unix) not in (int, float) or not math.isfinite(boundary_unix):
            boundary_unix = self.started_unix + boundary - self.started
        reason = payload.get("reason", payload.get("type", "configuration"))
        identity = payload.get("phase_id")
        dedup = (
            f"population:{change.get('roster_revision')}:{change.get('committed_tick')}:{boundary}"
            if change
            else identity
        )
        if dedup is not None and any(
            p.get("dedup_key") == dedup for p in self.data["phases"]
        ):
            return None
        self._counter += 1
        phase = {
            "phase_id": self._counter,
            "source_phase_id": identity,
            "dedup_key": dedup,
            "reason": reason,
            "stage": payload.get("stage", "transition"),
            "boundary_at_unix": boundary_unix,
            "boundary_monotonic_seconds": boundary,
            "clock_uncertainty_seconds": uncertainty,
            "received_at_unix": received_at_unix,
            "received_monotonic_seconds": received,
            "boundary_source": (
                ("worker_monotonic" if change else "aligned_monotonic")
                if valid
                else "receipt_fallback"
            ),
            "elapsed_seconds": max(0.0, boundary - self.started),
            "attribution_complete": valid
            and (self._oldest_evicted is None or boundary > self._oldest_evicted),
            "context": payload,
            "viewer_reports": 0,
            **self._empty(),
        }
        phases = self.data["phases"]
        phases.append(phase)
        phases.sort(
            key=lambda item: (item["boundary_monotonic_seconds"], item["phase_id"])
        )
        if len(phases) > MAX_PHASES:
            old = phases.pop(0)
            self._frozen.pop(old["phase_id"], None)
            self.data["phases_dropped"] += 1
        if not valid:
            position = phases.index(phase)
            if position:
                phases[position - 1]["attribution_complete"] = False
        for index, item in enumerate(phases):
            item["ended_at_unix"] = (
                phases[index + 1]["boundary_at_unix"]
                if index + 1 < len(phases)
                else None
            )
            item["ended_monotonic_seconds"] = (
                phases[index + 1]["boundary_monotonic_seconds"]
                if index + 1 < len(phases)
                else None
            )
            closing = phases[index + 1] if index + 1 < len(phases) else None
            item["end_boundary"] = (
                {
                    "source": closing["boundary_source"],
                    "clock_uncertainty_seconds": closing["clock_uncertainty_seconds"],
                    "viewer_clock_id": closing["context"].get("viewer_clock_id"),
                    "boundary_local_usec": closing["context"].get(
                        "boundary_local_usec"
                    ),
                }
                if closing is not None
                else None
            )
            item.update(
                copy.deepcopy(self._frozen.get(item["phase_id"], self._empty()))
            )
            if self._oldest_evicted is not None and boundary <= self._oldest_evicted:
                item["attribution_complete"] = False
        for sample in self._history:
            owner = self._owner(sample["at"])
            if owner is not None:
                sample["owner"] = owner
                self._attribute(sample, owner)
                if sample["context"] is not None:
                    sample["context"].update(
                        phase_id=owner["phase_id"], phase_mixed=self._mixed(sample)
                    )
        for item in phases:
            if "latest_viewer_metrics" in item:
                item["latest_viewer_metrics_mixed"] = self._viewer_mixed(
                    item, item["latest_viewer_metrics"]
                )
        return phase

    @staticmethod
    def _viewer_mixed(phase: dict, payload: dict) -> bool:
        """Check the whole retained frame window against both phase boundaries.

        Two readings of the same viewer clock share their mapping error; compare
        their original local timestamps directly. A worker commit belongs to a
        different clock, so expand the viewer window by measured uncertainty.
        """

        def number(value):
            return type(value) in (int, float) and math.isfinite(value)

        start = payload.get("window_start_monotonic_seconds")
        end = payload.get("window_end_monotonic_seconds")
        if not (
            number(start)
            and number(end)
            and start <= end
            and phase["attribution_complete"]
        ):
            return True
        context = phase["context"]
        clock_id = payload.get("viewer_clock_id")
        local_start = payload.get("window_start_local_usec")
        local_end = payload.get("window_end_local_usec")
        local_window = (
            isinstance(clock_id, str)
            and bool(clock_id)
            and number(local_start)
            and number(local_end)
            and 0 <= local_start <= local_end
        )
        uncertainty = payload.get("clock_uncertainty_seconds")
        if uncertainty is None and phase["boundary_source"] == "aligned_monotonic":
            # Compatibility with zero-uncertainty test/older local reports. With
            # nonzero uncertainty and no same-clock proof this remains mixed.
            uncertainty = phase["clock_uncertainty_seconds"]
        if not (number(uncertainty) and 0 <= uncertainty <= 5.0):
            return True
        local_boundary = context.get("boundary_local_usec")
        same_start_clock = (
            local_window
            and phase["boundary_source"] == "aligned_monotonic"
            and context.get("viewer_clock_id") == clock_id
            and number(local_boundary)
        )
        if same_start_clock:
            if local_start < local_boundary:
                return True
        elif (
            start - uncertainty
            < phase["boundary_monotonic_seconds"] + phase["clock_uncertainty_seconds"]
        ):
            return True
        if phase["ended_monotonic_seconds"] is None:
            return False
        closing = phase.get("end_boundary") or {}
        closing_local = closing.get("boundary_local_usec")
        same_end_clock = (
            local_window
            and closing.get("source") == "aligned_monotonic"
            and closing.get("viewer_clock_id") == clock_id
            and number(closing_local)
        )
        if same_end_clock:
            return local_end > closing_local
        closing_uncertainty = closing.get("clock_uncertainty_seconds", 0.0)
        return (
            end + uncertainty > phase["ended_monotonic_seconds"] - closing_uncertainty
        )

    def viewer_metrics(self, payload: dict):
        identity = payload.get("phase_id")
        phase = next(
            (
                item
                for item in reversed(self.data["phases"])
                if identity is not None and item["source_phase_id"] == identity
            ),
            None,
        )
        if phase is None:
            self.data["unattributed_viewer_reports"] += 1
            self.data["latest_unattributed_viewer_metrics"] = payload
            return
        phase["viewer_reports"] += 1
        phase["latest_viewer_metrics_mixed"] = self._viewer_mixed(phase, payload)
        phase["latest_viewer_metrics"] = payload

    def comparison(self, payload: dict, received_at_unix: float):
        source_id = payload.get("phase_id")
        phase = next(
            (
                item
                for item in reversed(self.data["phases"])
                if source_id is not None and item["source_phase_id"] == source_id
            ),
            None,
        )
        point = {
            "at_unix": received_at_unix,
            "phase_id": phase["phase_id"] if phase else None,
            "source_phase_id": source_id,
            "phase_attribution": "matched" if phase else "unknown",
            "elapsed_seconds": time.monotonic() - self.started,
            "metrics": payload,
        }
        points = self.data["comparison_points"]
        points.append(point)
        if len(points) > MAX_POINTS:
            points.pop(0)
            self.data["comparison_points_dropped"] += 1
        return point
