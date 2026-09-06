"""Production commuter identities, incremental delivery and cancellation."""

from copy import deepcopy
import json
import pickle

import pytest

from civic_center import shared_geometry
from civic_center.shared_geometry import (
    GeometryEncodingCancelled, GeometryLimits, SharedGeometryDecoder,
    SharedGeometryEncoder, WIRE_ENVELOPE_RESERVE,
)


def route(cycle=0, direction="outbound", resident="resident:with:colons"):
    points = ((0.0, 0.0, 0.0), (3.0, 0.0, 4.0), (6.0, 0.0, 0.0))
    nodes = ("home", "work")
    if direction == "return":
        points, nodes = tuple(reversed(points)), tuple(reversed(nodes))
    return {"id": f"{resident}:{direction}:{cycle}", "points": points, "node_ids": nodes, "length_m": 10.0}


def wire(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def apply(decoder, messages):
    for message in messages:
        decoder.apply_json(wire(message))


def test_repeating_days_and_large_cycle_jumps_use_two_identity_records_forever():
    limits = GeometryLimits(identities=2)
    encoder, decoder = SharedGeometryEncoder("daily", limits=limits), SharedGeometryDecoder("daily", limits=limits)
    previous = []
    for cycle in (*range(30), 100_000, 1_000_000):
        for direction in ("outbound", "return"):
            current = route(cycle, direction)
            messages = encoder.encode([current], retire_ids=previous)
            apply(decoder, messages)
            assert wire(decoder.expand()) == wire([current])
            assert encoder.stats() == decoder.stats()
            assert encoder.stats()["points"] == 3
            assert encoder.stats()["identity_records"] <= 2
            assert encoder.stats()["point_references"] == 3
            previous = [current["id"]]
    assert encoder.stats()["identity_records"] == 2


def test_current_cycle_can_reactivate_but_older_cycle_is_rejected_after_advancement():
    encoder, decoder = SharedGeometryEncoder("stale"), SharedGeometryDecoder("stale")
    old = route()
    apply(decoder, encoder.encode([old]))
    decoder.apply(encoder.forget([old["id"]]))
    apply(decoder, encoder.encode([old]))
    newer = route(10)
    apply(decoder, encoder.encode([newer], retire_ids=[old["id"]]))
    before = encoder.stats()
    with pytest.raises(ValueError, match="stale commuter cycle"):
        encoder.encode([old])
    forged = encoder.messages_since(encoder.point_count, [newer["id"]])[0]
    forged["geometries"][0]["id"] = old["id"]
    with pytest.raises(ValueError, match="stale commuter cycle"):
        decoder.apply(forged)
    assert encoder.stats() == decoder.stats() == before
    assert wire(decoder.expand()) == wire([newer])


def test_higher_cycle_cannot_reinterpret_the_pinned_route_or_its_coordinates():
    encoder, decoder = SharedGeometryEncoder("pinned"), SharedGeometryDecoder("pinned")
    initial = route()
    apply(decoder, encoder.encode([initial]))
    changed = route(1)
    changed["points"] = tuple(reversed(changed["points"]))
    before = encoder.stats()
    with pytest.raises(ValueError, match="identity cannot change"):
        encoder.encode([changed], retire_ids=[initial["id"]])
    assert encoder.stats() == before
    bad = encoder.messages_since(encoder.point_count, [initial["id"]])[0]
    bad["geometries"][0]["id"] = changed["id"]
    bad["geometries"][0]["point_indices"].reverse()
    with pytest.raises(ValueError, match="identity cannot change"):
        decoder.apply(bad)
    assert decoder.stats() == before


@pytest.mark.parametrize("identity", [
    "resident:0", "resident:drive:0", ":outbound:0", "resident:outbound:-1",
    "resident:outbound:01", "resident:outbound:1.0", "resident:outbound:١",
    "resident:outbound:9007199254740992",
])
def test_commuter_id_grammar_is_strict(identity):
    value = route()
    value["id"] = identity
    with pytest.raises(ValueError, match="commuter|IDs"):
        SharedGeometryEncoder("grammar").encode([value])


def test_retire_and_add_share_reference_budget_and_fail_atomically():
    limits = GeometryLimits(point_references=3)
    encoder, decoder = SharedGeometryEncoder("replace", limits=limits), SharedGeometryDecoder("replace", limits=limits)
    first, second = route(), route(0, "return")
    apply(decoder, encoder.encode([first]))
    before = encoder.stats()
    with pytest.raises(ValueError, match="point-reference"):
        encoder.encode([second])
    assert encoder.stats() == before
    messages = encoder.encode([second], retire_ids=[first["id"]])
    assert [m["type"] for m in messages] == ["forget_trip_geometries", "trip_geometry_indices"]
    apply(decoder, messages)
    assert encoder.stats() == decoder.stats()
    assert wire(decoder.expand()) == wire([second])


def test_late_client_delivery_cursor_is_detached_and_does_not_mutate_encoder():
    encoder, first_client = SharedGeometryEncoder("clients"), SharedGeometryDecoder("clients")
    first = route()
    apply(first_client, encoder.encode([first]))
    cursor = encoder.point_count
    second = route(resident="other-resident")
    second["points"] = (*second["points"], (7.0, 0.0, 0.0))
    apply(first_client, encoder.encode([second]))
    before = encoder.stats()
    delivery = encoder.messages_since(0, [first["id"], second["id"]])
    assert encoder.stats() == before
    new_client = SharedGeometryDecoder("clients")
    apply(new_client, delivery)
    assert wire(new_client.expand()) == wire([first, second])
    suffix = encoder.messages_since(cursor, [second["id"]])
    assert suffix[0]["start_index"] == cursor
    assert suffix[0]["points"] == [[7.0, 0.0, 0.0]]
    delivery[0]["points"][0][0] = 900
    assert wire(encoder.expand([first["id"]])) == wire([first])
    assert encoder.messages_since(encoder.point_count, []) == []
    with pytest.raises(ValueError, match="cursor"):
        encoder.messages_since(True, [])


@pytest.mark.parametrize("cancel_at", [1, 4, 10])
def test_cancellation_during_preparation_never_commits_retirements_or_points(cancel_at):
    encoder = SharedGeometryEncoder("cancel")
    first = route()
    encoder.encode([first])
    before = encoder.stats()
    other = route(resident="new-resident")
    other["points"] = tuple((float(i), 0.0, 0.0) for i in range(2048))
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= cancel_at

    with pytest.raises(GeometryEncodingCancelled):
        encoder.encode([other], retire_ids=[first["id"]], should_cancel=cancelled)
    assert encoder.stats() == before
    assert wire(encoder.expand()) == wire([first])


def test_encoder_private_transfer_retains_lifecycle_and_no_callable_state():
    encoder = SharedGeometryEncoder("pickle")
    initial = route(100)
    encoder.encode([initial], should_cancel=lambda: False)
    transferred = pickle.loads(pickle.dumps(encoder, protocol=pickle.HIGHEST_PROTOCOL))
    assert transferred.stats() == encoder.stats()
    assert wire(transferred.expand()) == wire(encoder.expand())
    current = route(1_000_000)
    assert transferred.encode([current], retire_ids=[initial["id"]]) == encoder.encode([current], retire_ids=[initial["id"]])


def test_unchanged_incremental_update_does_not_serialize_cached_coordinates(monkeypatch):
    encoder = SharedGeometryEncoder("idle")
    encoder.encode([route()])
    original = shared_geometry._json
    calls = []

    def small_only(value):
        encoded = original(value)
        calls.append(len(encoded))
        assert len(encoded) < 160
        return encoded

    monkeypatch.setattr(shared_geometry, "_json", small_only)
    assert encoder.encode([]) == []
    assert encoder.messages_since(encoder.point_count, []) == []
    assert not calls


def test_wire_budget_includes_retained_pool_headers_and_per_route_frames():
    encoder, decoder = SharedGeometryEncoder("wire"), SharedGeometryDecoder("wire")
    messages = encoder.encode([route(resident="first"), route(resident="second")])
    apply(decoder, messages)
    assert encoder.stats()["accounted_wire_bytes"] == sum(len(wire(m)) + 1 for m in messages) + WIRE_ENVELOPE_RESERVE
    assert encoder.stats() == decoder.stats()
