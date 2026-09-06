"""Optional backend selection, failure semantics and trusted process transfer."""

import multiprocessing
from pathlib import Path
import pickle

import pytest

from civic_center import native_routing
from civic_center.checkpoint import capture_checkpoint, load_checkpoint, save_checkpoint, write_captured_checkpoint
from civic_center.model import CivicSimulation
from civic_center.routing import WalkingGraph
from civic_center.scenario import make_scenario, scenario_hash

requires_native = pytest.mark.skipif(native_routing.find_library() is None, reason="Optional native router is not built")


def small_graph(backend=None):
    return WalkingGraph(
        [{"id": "a", "position": [0, 0, 0]}, {"id": "b", "position": [6, 0, 0]},
         {"id": "isolated", "position": [100, 0, 0]}],
        [{"id": "hill", "from": "a", "to": "b", "points": [[0, 0, 0], [3, 0, 4], [6, 0, 0]]}],
        backend=backend,
    )


@pytest.mark.parametrize("backend", ["", "gpu", "Rust", True, 1, {}])
def test_invalid_backend_is_rejected(backend):
    with pytest.raises(ValueError, match="backend"):
        small_graph(backend)


def test_auto_uses_python_when_library_absent_and_keeps_cached_routes(monkeypatch):
    monkeypatch.setattr(native_routing, "find_library", lambda: None)
    graph = small_graph("auto")
    assert graph.backend == "python"
    result = graph.route("a", "b")
    assert result.length == 10
    assert graph.route("a", "b") is result
    assert graph.route("a", "isolated") is None
    assert graph._native_routes is None


def test_explicit_python_overrides_environment_without_native_discovery(monkeypatch):
    monkeypatch.setenv("CIVIC_ROUTING_BACKEND", "rust")

    def forbidden_discovery():
        raise AssertionError("Python backend should not inspect native libraries")

    monkeypatch.setattr(native_routing, "find_library", forbidden_discovery)
    assert small_graph("python").route("a", "b").length == 10


def test_environment_is_used_when_constructor_choice_is_omitted(monkeypatch):
    monkeypatch.setenv("CIVIC_ROUTING_BACKEND", "python")
    assert small_graph().backend == "python"
    monkeypatch.setenv("CIVIC_ROUTING_BACKEND", "unknown")
    with pytest.raises(ValueError, match="backend"):
        small_graph()


def test_forced_rust_absence_is_an_explicit_error(monkeypatch):
    monkeypatch.setattr(native_routing, "find_library", lambda: None)
    graph = small_graph("rust")
    with pytest.raises(RuntimeError, match="unavailable"):
        graph.route("a", "b")
    assert graph._cache == {}


def test_explicit_library_path_never_selects_an_unrelated_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVIC_ROUTING_DLL", str(tmp_path / "missing-library.dll"))
    assert native_routing.find_library() is None


def test_existing_invalid_library_is_not_treated_as_absent(tmp_path, monkeypatch):
    path = tmp_path / "invalid-library.dll"
    path.write_bytes(b"not a shared library")
    monkeypatch.setattr(native_routing, "find_library", lambda: path)
    graph = small_graph("auto")
    with pytest.raises(OSError):
        graph.route("a", "b")
    assert graph.backend == "rust"
    assert graph._cache == {}


def test_native_route_failure_never_falls_back_or_populates_cache(monkeypatch):
    class FailingNative:
        def __init__(self, *_):
            pass

        def route(self, *_):
            raise RuntimeError("injected native route failure")

    monkeypatch.setattr(native_routing, "find_library", lambda: Path("selected-native.dll"))
    monkeypatch.setattr(native_routing, "NativeRoutes", FailingNative)
    graph = small_graph("auto")
    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="injected native"):
            graph.route("a", "b")
    assert graph.backend == "rust"
    assert graph._cache == {}


def test_unsupported_native_abi_is_not_a_python_fallback(monkeypatch):
    class WrongAbi:
        def civic_routing_abi_version(self):
            return 2

    # ctypes entry points permit argtypes/restype assignment, so a function
    # object models that part of the adapter without loading an actual DLL.
    library = WrongAbi()
    library.civic_routing_abi_version = lambda: 2
    monkeypatch.setattr(native_routing, "find_library", lambda: Path("abi-two.dll"))
    monkeypatch.setattr(native_routing.ctypes, "CDLL", lambda *_: library)
    graph = small_graph("auto")
    with pytest.raises(RuntimeError, match="ABI"):
        graph.route("a", "b")
    assert graph.backend == "rust"
    assert graph._cache == {}


@requires_native
def test_rust_backend_preserves_dense_geometry_unreachable_and_cache_identity():
    python, native = small_graph("python"), small_graph("rust")
    assert native._native_routes is None
    for origin, destination in (("a", "b"), ("b", "a"), ("a", "a"), ("a", "isolated")):
        expected = python.route(origin, destination)
        actual = native.route(origin, destination)
        assert actual == expected
        assert native.route(origin, destination) is actual
    assert native.backend == "rust"
    assert native._native_routes is not None


@requires_native
@pytest.mark.parametrize("status", [-1, 2, 42])
def test_native_failure_status_is_reported_without_python_retry(monkeypatch, status):
    graph = small_graph("rust")
    graph.route("a", "a")
    monkeypatch.setattr(graph._native_routes._library, "civic_graph_route", lambda *_: status)
    with pytest.raises(RuntimeError, match="status"):
        graph.route("a", "b")
    assert ("a", "b") not in graph._cache


@requires_native
def test_native_success_with_incomplete_path_is_rejected(monkeypatch):
    graph = small_graph("rust")
    graph.route("a", "a")
    monkeypatch.setattr(graph._native_routes._library, "civic_graph_route", lambda *_: 0)
    with pytest.raises(RuntimeError, match="inconsistent endpoints"):
        graph.route("a", "b")
    assert ("a", "b") not in graph._cache


@requires_native
def test_native_graph_pickle_keeps_cache_and_recreates_handle_only_for_uncached_query():
    original = small_graph("rust")
    expected = original.route("a", "b")
    state = original.__getstate__()
    assert "_native_routes" not in state
    assert "_native_library" not in state
    received = pickle.loads(pickle.dumps(original))
    assert received._native_routes is None
    assert received.route("a", "b") == expected
    assert received._native_routes is None
    assert received.route("b", "a") == small_graph("python").route("b", "a")
    assert received._native_routes is not None
    assert original.route("a", "b") is expected


@requires_native
def test_auto_transfer_can_use_python_when_destination_has_no_library(monkeypatch):
    original = small_graph("auto")
    original.route("a", "b")
    encoded = pickle.dumps(original)
    monkeypatch.setattr(native_routing, "find_library", lambda: None)
    received = pickle.loads(encoded)
    assert received._native_routes is None
    assert received.backend == "python"
    assert received.route("b", "a") == small_graph("python").route("b", "a")


@requires_native
def test_backend_choice_changes_neither_scenario_hash_nor_checkpoint_bytes(tmp_path, monkeypatch):
    scenario = make_scenario(1, repeat_days=True)
    identity = scenario_hash(scenario)
    python = CivicSimulation(scenario, routing_backend="python")
    native = CivicSimulation(scenario, routing_backend="rust")
    tick = 3 * 86_400 * python.tick_hz + 12_345
    python.step_ticks(tick)
    native.step_ticks(tick)
    assert python.snapshot() == native.snapshot()
    assert scenario_hash(python.scenario) == scenario_hash(native.scenario) == identity
    first = save_checkpoint(python, tmp_path / "python.json")
    second = save_checkpoint(native, tmp_path / "native.json")
    assert first.read_bytes() == second.read_bytes()
    monkeypatch.setenv("CIVIC_ROUTING_BACKEND", "rust")
    restored = load_checkpoint(first)
    assert restored.graph.backend == "rust"
    assert restored.snapshot() == python.snapshot()
    captured = write_captured_checkpoint(capture_checkpoint(python), tmp_path / "captured.json")
    assert captured.read_bytes() == first.read_bytes()


@requires_native
def test_geography_and_landuse_generation_is_identical_across_backends(tmp_path, monkeypatch):
    from civic_center.city_scenario import build_city_scenario
    from tests.civic_center.test_city_landuse import sources

    geography, landuse, _data = sources(tmp_path)
    monkeypatch.setenv("CIVIC_ROUTING_BACKEND", "python")
    python = build_city_scenario(geography, 200, 19, landuse_path=landuse)
    monkeypatch.setenv("CIVIC_ROUTING_BACKEND", "rust")
    native = build_city_scenario(geography, 200, 19, landuse_path=landuse)
    assert native == python


def _spawn_route_probe(connection, model, origin, destination):
    try:
        lazy = model.graph._native_routes is None
        state = model.snapshot()
        route = model.graph.route(origin, destination)
        connection.send((lazy, state, route, model.graph.backend))
    finally:
        connection.close()


@requires_native
def test_spawned_worker_receives_active_model_without_native_handle_and_continues():
    scenario = make_scenario(1, repeat_days=True)
    model = CivicSimulation(scenario, routing_backend="rust")
    model.step_ticks(12_345)
    origin, destination = "entrance:building-3", "entrance:building-9"
    assert (origin, destination) not in model.graph._cache
    expected = WalkingGraph(scenario["nodes"], scenario["edges"], backend="python").route(origin, destination)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_spawn_route_probe, args=(child, model, origin, destination))
    try:
        process.start()
        child.close()
        assert parent.poll(20), "Spawned route probe did not respond"
        lazy, state, route, backend = parent.recv()
        assert lazy
        assert state == model.snapshot()
        assert route == expected
        assert backend == "rust"
        process.join(10)
        assert process.exitcode == 0
    finally:
        parent.close()
        child.close()
        if process.is_alive():
            process.terminate()
            process.join(10)
