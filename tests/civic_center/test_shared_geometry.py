"""Exact route expansion and finite session resources for the codec experiment."""

from copy import deepcopy
from functools import partial
import json
import math

import pytest

from civic_center.shared_geometry import (
    GeometryLimits, SharedGeometryDecoder as GeometryDecoder, SharedGeometryEncoder as GeometryEncoder,
    MAX_CACHE_BYTES, MAX_FRAME_BYTES, MAX_POINTS, MAX_POINT_REFERENCES,
)

# Generic geometry fixtures intentionally use opaque IDs. The production daily
# identity policy is exercised separately in test_shared_geometry_lifecycle.py.
SharedGeometryDecoder = partial(GeometryDecoder, identity_mode="opaque-v1")
SharedGeometryEncoder = partial(GeometryEncoder, identity_mode="opaque-v1")


def wire(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode()


def route(identity="outbound:0", points=None):
    return {"id": identity, "points": points or [[0.0, 0.0, 0.0], [3.0, 0.0, 4.0], [6.0, 0.0, 0.0]],
            "node_ids": ["home", "work"], "length_m": 10.0}


def transfer(encoder, decoder, definitions):
    messages = encoder.encode(definitions)
    for message in messages:
        decoder.apply_json(wire(message))
    assert decoder.stats() == encoder.stats()
    return messages


def test_shared_reverse_and_overlapping_routes_expand_to_exact_old_records():
    encoder, decoder = SharedGeometryEncoder("day"), SharedGeometryDecoder("day")
    first = route()
    second = route("return:0", list(reversed(first["points"])))
    second["node_ids"].reverse()
    third = route("nearby:0", [first["points"][1], first["points"][2]])
    definitions = [first, second, third]
    messages = transfer(encoder, decoder, definitions)
    assert [m["type"] for m in messages] == ["route_coordinate_pool"] + ["trip_geometry_indices"] * 3
    assert decoder.stats()["points"] == 3
    assert decoder.stats()["point_references"] == 8
    assert wire(decoder.expand()) == wire(definitions)
    assert wire(encoder.expand()) == wire(definitions)
    assert encoder.encode(definitions) == []


def test_float_bits_negative_zero_and_integer_forms_are_preserved():
    points = [[0.0, -0.0, 0], [0, 0.0, -0.0], [math.nextafter(1.0, 2.0), 1e-300, -1e300],
              [0.0, -0.0, 0]]
    value = route(points=points)
    encoder, decoder = SharedGeometryEncoder("precision"), SharedGeometryDecoder("precision")
    transfer(encoder, decoder, [value])
    assert decoder.stats()["points"] == 3
    assert wire(decoder.expand()) == wire([value])
    expanded = decoder.expand()[0]["points"]
    assert math.copysign(1, expanded[0][1]) == -1
    assert type(expanded[0][2]) is int
    assert type(expanded[0][0]) is float


def test_inputs_messages_and_expanded_records_are_detached():
    encoder, decoder = SharedGeometryEncoder("detached"), SharedGeometryDecoder("detached")
    value = route()
    expected = deepcopy(value)
    messages = transfer(encoder, decoder, [value])
    value["points"][0][0] = 900
    messages[0]["points"][0][0] = 800
    messages[1]["geometries"][0]["point_indices"][0] = 2
    expanded = decoder.expand()
    expanded[0]["points"][0][0] = 700
    expanded[0]["node_ids"][0] = "changed"
    assert wire(decoder.expand()) == wire(encoder.expand()) == wire([expected])


def test_forgetting_releases_paths_but_retains_points_and_identity_proof():
    encoder, decoder = SharedGeometryEncoder("lifetime"), SharedGeometryDecoder("lifetime")
    first = route()
    transfer(encoder, decoder, [first])
    decoder.apply(encoder.forget([first["id"]]))
    assert decoder.stats()["points"] == 3
    assert decoder.stats()["active_trips"] == decoder.stats()["point_references"] == 0
    assert decoder.stats()["seen_trip_identities"] == 1
    with pytest.raises(ValueError, match="Unknown active"):
        decoder.expand([first["id"]])
    messages = transfer(encoder, decoder, [first])
    assert [m["type"] for m in messages] == ["trip_geometry_indices"]
    assert decoder.expand() == [first]


@pytest.mark.parametrize("forgotten", [False, True])
def test_changed_trip_identity_is_rejected_even_after_forgetting(forgotten):
    encoder, decoder = SharedGeometryEncoder("same-id"), SharedGeometryDecoder("same-id")
    first = route()
    messages = transfer(encoder, decoder, [first])
    if forgotten:
        decoder.apply(encoder.forget([first["id"]]))
    before = encoder.stats()
    changed = route(points=list(reversed(first["points"])))
    with pytest.raises(ValueError, match="identity cannot change"):
        encoder.encode([changed])
    assert encoder.stats() == before
    bad = deepcopy(messages[-1])
    bad["geometries"][0]["point_indices"].reverse()
    with pytest.raises(ValueError, match="identity cannot change"):
        decoder.apply(bad)
    assert decoder.stats() == before


def test_bounded_identity_lifetime_requires_new_session_and_rejects_old_frames():
    limits = GeometryLimits(identities=2)
    encoder, decoder = SharedGeometryEncoder("one", limits=limits), SharedGeometryDecoder("one", limits=limits)
    for cycle in range(2):
        value = route(f"trip:{cycle}")
        old_messages = transfer(encoder, decoder, [value])
        decoder.apply(encoder.forget([value["id"]]))
    assert decoder.stats()["points"] == 3
    assert decoder.stats()["seen_trip_identities"] == 2
    with pytest.raises(ValueError, match="identity lifetime"):
        encoder.encode([route("trip:2")])
    with pytest.raises(ValueError, match="new session"):
        encoder.reset("one")
    encoder.reset("two")
    decoder.reset("two")
    assert decoder.stats()["points"] == decoder.stats()["seen_trip_identities"] == 0
    with pytest.raises(ValueError, match="different session"):
        decoder.apply(old_messages[0])
    replacement = route("trip:0", [[10, 10, 10]])
    replacement["length_m"] = 0
    transfer(encoder, decoder, [replacement])
    assert decoder.expand() == [replacement]


@pytest.mark.parametrize("field,value,message", [
    ("id", "", "IDs"), ("id", True, "IDs"), ("id", "bad\nID", "IDs"),
    ("points", [[float("nan"), 0, 0]], "finite"),
    ("points", [[float("inf"), 0, 0]], "finite"),
    ("points", [[True, 0, 0]], "finite"),
    ("points", [[10 ** 400, 0, 0]], "JSON-safe"),
    ("points", [[0, 0]], "three coordinates"),
    ("node_ids", [False], "IDs"), ("node_ids", [], "route node IDs"),
    ("length_m", -1, "nonnegative"), ("length_m", True, "finite"),
])
def test_invalid_expanded_definitions_fail_without_mutating_encoder(field, value, message):
    encoder = SharedGeometryEncoder("validation")
    source = route()
    source[field] = value
    before = encoder.stats()
    with pytest.raises(ValueError, match=message):
        encoder.encode([source])
    assert encoder.stats() == before


@pytest.mark.parametrize("reference", [-1, 3, True, 0.0, "0"])
def test_bad_point_references_cannot_create_or_modify_a_path(reference):
    encoder, decoder = SharedGeometryEncoder("indices"), SharedGeometryDecoder("indices")
    messages = encoder.encode([route()])
    decoder.apply(messages[0])
    messages[1]["geometries"][0]["point_indices"][0] = reference
    before = decoder.stats()
    with pytest.raises(ValueError, match="out of range"):
        decoder.apply(messages[1])
    assert decoder.stats() == before


def test_pool_indices_cannot_be_overwritten_skipped_or_aliased():
    encoder, decoder = SharedGeometryEncoder("pool"), SharedGeometryDecoder("pool")
    messages = transfer(encoder, decoder, [route()])
    for start in (0, 4, True):
        bad = deepcopy(messages[0])
        bad["start_index"] = start
        with pytest.raises(ValueError, match="exact next index"):
            decoder.apply(bad)
    bad["start_index"] = 3
    with pytest.raises(ValueError, match="duplicate coordinate identity"):
        decoder.apply(bad)
    assert decoder.stats() == encoder.stats()


@pytest.mark.parametrize("limits,values,message", [
    (GeometryLimits(points=2), [route()], "point limit"),
    (GeometryLimits(point_references=5), [route("a"), route("b")], "point-reference"),
    (GeometryLimits(node_references=3), [route("a"), route("b")], "node-reference"),
    (GeometryLimits(cache_bytes=4097), [route()], "wire cache budget"),
    (GeometryLimits(frame_bytes=100), [route()], "frame limit"),
])
def test_encoder_resource_limits_are_atomic(limits, values, message):
    encoder = SharedGeometryEncoder("limits", limits=limits)
    before = encoder.stats()
    with pytest.raises(ValueError, match=message):
        encoder.encode(values)
    assert encoder.stats() == before


def test_decoder_reference_and_point_limits_cannot_be_bypassed_with_valid_frames():
    encoder = SharedGeometryEncoder("bounded")
    messages = encoder.encode([route("a"), route("b")])
    decoder = SharedGeometryDecoder("bounded", limits=GeometryLimits(point_references=5))
    decoder.apply(messages[0])
    decoder.apply(messages[1])
    with pytest.raises(ValueError, match="point-reference"):
        decoder.apply(messages[2])
    assert decoder.stats()["active_trips"] == 1
    decoder = SharedGeometryDecoder("bounded", limits=GeometryLimits(points=2))
    with pytest.raises(ValueError, match="pool points|point limit"):
        decoder.apply(messages[0])
    assert decoder.stats()["points"] == 0


def test_large_messages_split_at_frame_boundaries_and_keep_contiguous_indices():
    encoder, decoder = SharedGeometryEncoder("chunks", limits=GeometryLimits(frame_bytes=450)), SharedGeometryDecoder("chunks", limits=GeometryLimits(frame_bytes=450))
    values = [route(f"trip-{i}", [[i * 10 + j, 0, 0] for j in range(10)]) for i in range(8)]
    messages = transfer(encoder, decoder, values)
    assert len(messages) > 2
    assert all(len(wire(message)) <= 450 for message in messages)
    assert wire(decoder.expand()) == wire(values)


@pytest.mark.parametrize("raw", [b'{', b'{"type":1,"type":2}', b'\xff', b'[]'])
def test_invalid_serialized_frames_are_rejected(raw):
    with pytest.raises(ValueError):
        SharedGeometryDecoder("json").apply_json(raw)


def test_serialized_byte_limit_applies_before_json_parsing_and_limits_cannot_grow():
    decoder = SharedGeometryDecoder("json", limits=GeometryLimits(frame_bytes=100))
    with pytest.raises(ValueError, match="exceeds the limit"):
        decoder.apply_json(b" " * 101)
    for field, maximum in (("points", MAX_POINTS), ("point_references", MAX_POINT_REFERENCES),
                           ("cache_bytes", MAX_CACHE_BYTES), ("frame_bytes", MAX_FRAME_BYTES)):
        with pytest.raises(ValueError, match="limit must be"):
            GeometryLimits(**{field: maximum + 1})


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(protocol_version=True),
    lambda m: m.update(session_id="other"),
    lambda m: m.update(unknown="field"),
    lambda m: m["geometries"][0].update(id=""),
    lambda m: m["geometries"][0].update(length_m=float("inf")),
    lambda m: m["geometries"].append(deepcopy(m["geometries"][0])),
])
def test_decoder_rejects_invalid_headers_ids_lengths_and_duplicate_definitions(mutation):
    encoder, decoder = SharedGeometryEncoder("strict"), SharedGeometryDecoder("strict")
    messages = encoder.encode([route()])
    decoder.apply(messages[0])
    before = decoder.stats()
    mutation(messages[1])
    with pytest.raises(ValueError):
        decoder.apply(messages[1])
    assert decoder.stats() == before


def test_duplicate_expansion_requests_cannot_multiply_decoded_reference_memory():
    encoder, decoder = SharedGeometryEncoder("expand"), SharedGeometryDecoder("expand")
    transfer(encoder, decoder, [route()])
    assert decoder.expand(["outbound:0"] * 20) == [route()]


def test_full_day_coordinate_pool_is_bounded_while_paths_rotate():
    encoder, decoder = SharedGeometryEncoder("whole-day"), SharedGeometryDecoder("whole-day")
    morning = [route(f"resident-{i}:outbound:0", [[i, 0, 0], [10, 0, 0]]) for i in range(8)]
    evening = [dict(value, id=value["id"].replace("outbound", "return"), points=list(reversed(value["points"]))) for value in morning]
    transfer(encoder, decoder, morning)
    point_count = encoder.stats()["points"]
    decoder.apply(encoder.forget([value["id"] for value in morning]))
    messages = transfer(encoder, decoder, evening)
    assert all(message["type"] != "route_coordinate_pool" for message in messages)
    assert encoder.stats()["points"] == point_count == 9
    assert encoder.stats()["seen_trip_identities"] == 16
    assert wire(decoder.expand()) == wire(evening)
