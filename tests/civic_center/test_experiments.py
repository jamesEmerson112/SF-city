"""Experiment summaries respect authoritative time and bounded retention."""

import pytest

from civic_center.experiments import MAX_PHASES, MAX_POINTS, ExperimentArchive


def _archive(history_limit=360):
    return ExperimentArchive(1000.0, history_limit, started_monotonic=100.0)


def _phase(archive, boundary, *, identity="phase", received=None, **fields):
    return archive.phase(
        {
            "phase_id": identity,
            "boundary_monotonic_seconds": boundary,
            "clock_uncertainty_seconds": 0.0,
            **fields,
        },
        1000 + boundary - 100,
        received_monotonic=received or boundary,
    )


def test_delayed_commit_repartitions_retained_samples_and_excludes_mixed_interval():
    archive = _archive()
    contexts = []
    for at, value in [
        (101, 1),
        (102, 10),
        (103, 20),
        (104, 30),
        (105.5, 100),
        (106.5, 40),
        (107.5, 50),
    ]:
        context = {}
        archive.sample(at, {"cpu.percent": value}, 1.0, context)
        contexts.append(context)
    phase = _phase(
        archive,
        105,
        received=108,
        population_change={
            "roster_revision": 1,
            "committed_tick": 321,
            "committed_monotonic_seconds": 105,
            "committed_at_unix": 1005,
        },
    )
    previous = archive.data["phases"][0]
    assert previous["hardware_samples"] == 4
    assert previous["mixed_samples"] == 1
    assert previous["hardware_summary"]["cpu.percent"]["mean"] == 20
    assert phase["boundary_source"] == "worker_monotonic"
    assert phase["hardware_samples"] == 3
    assert phase["mixed_samples"] == 1
    assert phase["hardware_summary"]["cpu.percent"] == {
        "count": 2,
        "min": 40,
        "max": 50,
        "mean": 45,
        "last": 50,
    }
    assert contexts[-1]["phase_id"] == phase["phase_id"]
    assert contexts[-3]["phase_mixed"] is True


def test_wall_clock_jump_does_not_move_authoritative_monotonic_boundary():
    archive = _archive()
    archive.sample(101, {"cpu.percent": 1}, 1)
    archive.sample(102, {"cpu.percent": 2}, 1)
    phase = archive.phase(
        {
            "population_change": {
                "committed_monotonic_seconds": 102.5,
                "committed_at_unix": 90000,
                "roster_revision": 1,
            }
        },
        90001,
        received_monotonic=104,
    )
    assert phase["boundary_monotonic_seconds"] == 102.5
    assert phase["boundary_at_unix"] == 90000
    assert phase["elapsed_seconds"] == 2.5
    assert phase["attribution_complete"]


def test_unaligned_boundary_is_explicitly_incomplete_not_comparable():
    archive = _archive()
    phase = archive.phase({"boundary_at_unix": 1002}, 1003, received_monotonic=103)
    archive.sample(104, {"cpu.percent": 1}, 1)
    archive.sample(105, {"cpu.percent": 2}, 1)
    assert phase["boundary_source"] == "receipt_fallback"
    assert phase["attribution_complete"] is False
    assert phase["hardware_summary"] == {}


def test_clock_uncertainty_excludes_samples_on_both_sides_of_boundary():
    archive = _archive()
    archive.sample(101, {}, 1)
    archive.sample(102, {"cpu.percent": 10}, 1)
    archive.sample(103, {"cpu.percent": 20}, 1)
    phase = _phase(archive, 102.1, received=104, clock_uncertainty_seconds=0.2)
    assert archive.data["phases"][0]["hardware_summary"] == {}
    assert phase["hardware_summary"] == {}
    archive.sample(104, {"cpu.percent": 30}, 1)
    assert phase["hardware_summary"]["cpu.percent"]["count"] == 1


def test_eviction_preserves_peaks_and_old_boundaries_report_incomplete_attribution():
    archive = _archive(history_limit=2)
    for at, value in [(101, 1), (102, 99), (103, 3), (104, 4), (105, 5)]:
        archive.sample(at, {"cpu.percent": value}, 1)
    phase = _phase(archive, 105.5, received=106)
    previous = archive.data["phases"][0]
    assert previous["hardware_summary"]["cpu.percent"]["max"] == 99
    assert previous["hardware_summary"]["cpu.percent"]["count"] == 4
    assert phase["attribution_complete"]
    old = _phase(archive, 102, received=107, identity="late")
    assert old["attribution_complete"] is False
    assert all(not item["attribution_complete"] for item in archive.data["phases"])


def test_delayed_viewer_reports_use_matching_phase_and_reject_crossing_windows():
    archive = _archive()
    first = _phase(archive, 101, identity="a")
    second = _phase(archive, 103, identity="b")
    archive.viewer_metrics(
        {
            "phase_id": "a",
            "window_start_monotonic_seconds": 101.5,
            "window_end_monotonic_seconds": 102.5,
            "performance": {"p95_ms": 20},
        }
    )
    assert first["viewer_reports"] == 1
    assert not first["latest_viewer_metrics_mixed"]
    assert second["viewer_reports"] == 0
    archive.viewer_metrics(
        {
            "phase_id": "b",
            "window_start_monotonic_seconds": 102,
            "window_end_monotonic_seconds": 104,
        }
    )
    assert second["latest_viewer_metrics_mixed"]
    archive.viewer_metrics({"performance": {"p95_ms": 99}})
    assert archive.data["unattributed_viewer_reports"] == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"noop": True},
        {"outcome": "failed"},
        {"outcome": "cancelled"},
        {"outcome": "rejected"},
    ],
)
def test_failed_or_noop_operation_does_not_start_a_phase(fields):
    archive = _archive()
    assert _phase(archive, 102, **fields) is None
    assert len(archive.data["phases"]) == 1


def test_phase_and_comparison_retention_is_bounded():
    archive = _archive()
    for index in range(MAX_PHASES + 10):
        _phase(archive, 101 + index, identity=index)
    for index in range(MAX_POINTS + 10):
        archive.comparison({"index": index}, 1001 + index)
    assert len(archive.data["phases"]) == MAX_PHASES
    assert archive.data["phases_dropped"] == 11
    assert len(archive.data["comparison_points"]) == MAX_POINTS
    assert archive.data["comparison_points_dropped"] == 10


def test_late_phase_boundary_rechecks_already_received_frame_window():
    archive = _archive()
    phase = _phase(archive, 101, identity="a")
    archive.viewer_metrics(
        {
            "phase_id": "a",
            "window_start_monotonic_seconds": 102,
            "window_end_monotonic_seconds": 106,
        }
    )
    assert not phase["latest_viewer_metrics_mixed"]
    _phase(archive, 104, received=108, identity="b")
    assert phase["latest_viewer_metrics_mixed"]
    assert phase["viewer_reports"] == 1


def test_collector_interval_start_is_used_instead_of_logger_receipt():
    archive = _archive()
    archive.sample(101.2, {"cpu.percent": 1}, 1)
    phase = _phase(archive, 101.1, received=101.3)
    context = archive.sample(102.2, {"cpu.percent": 10}, 1, interval_start=101.0)
    assert context["phase_mixed"]
    assert phase["hardware_summary"] == {}


def _local_report(identity, start, end, local_start, local_end, clock="viewer-clock"):
    return {
        "phase_id": identity,
        "viewer_clock_id": clock,
        "clock_uncertainty_seconds": 0.2,
        "window_start_monotonic_seconds": start,
        "window_end_monotonic_seconds": end,
        "window_start_local_usec": local_start,
        "window_end_local_usec": local_end,
    }


def test_settled_same_viewer_clock_cancels_shared_mapping_uncertainty():
    archive = _archive()
    phase = _phase(
        archive,
        101,
        identity="a",
        viewer_clock_id="viewer-clock",
        boundary_local_usec=1000000,
        clock_uncertainty_seconds=0.2,
    )
    report = _local_report("a", 101, 102.5, 1000000, 2500000)
    archive.viewer_metrics(report)
    assert not phase["latest_viewer_metrics_mixed"]
    # A later local boundary uses the same clock even if its mapping changed
    # slightly after reconnect. Original local readings remain directly comparable.
    _phase(
        archive,
        103,
        identity="b",
        viewer_clock_id="viewer-clock",
        boundary_local_usec=3000000,
        clock_uncertainty_seconds=0.2,
    )
    assert not phase["latest_viewer_metrics_mixed"]
    assert phase["viewer_reports"] == 1


def test_local_window_before_boundary_or_from_other_clock_remains_mixed():
    archive = _archive()
    phase = _phase(
        archive,
        101,
        identity="a",
        viewer_clock_id="viewer-clock",
        boundary_local_usec=1000000,
        clock_uncertainty_seconds=0.2,
    )
    archive.viewer_metrics(_local_report("a", 101, 102, 999999, 2000000))
    assert phase["latest_viewer_metrics_mixed"]
    archive.viewer_metrics(
        _local_report("a", 101, 102, 1000000, 2000000, "other-viewer")
    )
    assert phase["latest_viewer_metrics_mixed"]
    _phase(
        archive,
        103,
        identity="b",
        viewer_clock_id="viewer-clock",
        boundary_local_usec=3000000,
        clock_uncertainty_seconds=0.2,
    )
    archive.viewer_metrics(_local_report("a", 101, 103, 1000000, 3000001))
    assert phase["latest_viewer_metrics_mixed"]


def test_worker_commit_retains_viewer_clock_uncertainty_on_both_window_edges():
    archive = _archive()
    before = _phase(
        archive,
        101,
        identity="before",
        viewer_clock_id="viewer-clock",
        boundary_local_usec=1000000,
        clock_uncertainty_seconds=0.2,
    )
    committed = _phase(
        archive,
        103,
        received=104,
        identity="commit",
        viewer_clock_id="viewer-clock",
        boundary_local_usec=4000000,
        population_change={"roster_revision": 1, "committed_monotonic_seconds": 103},
    )
    archive.viewer_metrics(_local_report("before", 101, 102.9, 1000000, 2900000))
    assert before["latest_viewer_metrics_mixed"]
    archive.viewer_metrics(_local_report("before", 101, 102.7, 1000000, 2700000))
    assert not before["latest_viewer_metrics_mixed"]
    archive.viewer_metrics(_local_report("commit", 103.1, 104, 4100000, 5000000))
    assert committed["latest_viewer_metrics_mixed"]
    archive.viewer_metrics(_local_report("commit", 103.3, 104, 4300000, 5000000))
    assert not committed["latest_viewer_metrics_mixed"]
    no_uncertainty = _local_report("commit", 103.3, 104, 4300000, 5000000)
    no_uncertainty.pop("clock_uncertainty_seconds")
    archive.viewer_metrics(no_uncertainty)
    assert committed["latest_viewer_metrics_mixed"]
