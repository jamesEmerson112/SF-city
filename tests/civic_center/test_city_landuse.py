"""Source use eligibility, group weights and generated cohort assignments."""

from collections import Counter
import hashlib
import json

import pytest

from civic_center.city_scenario import CITY_POPULATIONS, build_city_scenario
from civic_center.checkpoint import load_checkpoint, save_checkpoint
from civic_center.landuse import normalize_rows
from civic_center.model import CivicSimulation
from civic_center.scenario import scenario_hash
from tests.civic_center.test_city_scenario import geography_fixture


def sources(root, *, centers=None, rows=None, areas=None):
    manifest_path, _graph, buildings = geography_fixture(root, centers=centers)
    manifest = json.loads(manifest_path.read_text())
    for relative in ("fixture/buildings-index.json", "fixture/tile.json"):
        path = root / relative
        artifact = json.loads(path.read_text())
        for index, building in enumerate(artifact["buildings"]):
            building["mblr"] = f"0001{index:03d}"
            building["area_m2"] = areas[index] if areas is not None else 100
        raw = json.dumps(artifact, sort_keys=True).encode()
        path.write_bytes(raw)
        manifest["files"][relative] = hashlib.sha256(raw).hexdigest()
    manifest["sha256"] = scenario_hash(manifest)
    manifest_path.write_text(json.dumps(manifest))
    if rows is None:
        rows = [(f"0001{index:03d}", 10 if index % 2 == 0 else 0,
                 0 if index % 2 == 0 else 10000) for index in range(len(buildings))]
    raw_rows = [{
        "ludb_id": f"record-{index}", "mapblklot": parcel,
        "resunits": str(units), "resunits_s": "0", "total_comm": str(commercial),
        "retail": str(commercial), "cie": "0", "med": "0", "mips": "0",
        "pdr": "0", "visitor": "0", "data_as_of": "2026-08-17T00:00:00.000",
        "geography_type": "parcel fixture",
    } for index, (parcel, units, commercial) in enumerate(rows)]
    normalized = normalize_rows(raw_rows, {"dataset_id": "fixture", "license_id": "CC0_10"})
    landuse_path = root / "landuse.json"
    landuse_path.write_text(json.dumps(normalized, indent=2))
    return manifest_path, landuse_path, normalized


def test_only_positive_source_eligible_homes_and_jobs_are_assigned(tmp_path):
    manifest, landuse, normalized = sources(tmp_path)
    scenario = build_city_scenario(manifest, 200, landuse_path=landuse)
    buildings = {building["id"]: building for building in scenario["buildings"]}
    for resident in scenario["residents"]:
        home, work = buildings[resident["home_id"]], buildings[resident["work_id"]]
        assert home["land_use"]["home_eligible"] and home["land_use"]["home_weight"] > 0
        assert work["land_use"]["work_eligible"] and work["land_use"]["work_weight"] > 0
        assert resident["home_landuse_record_id"] == home["land_use"]["record_id"]
        assert resident["work_landuse_record_id"] == work["land_use"]["record_id"]
        assert "not observed" in resident["allocation_source"]
        assert 150 <= resident["commute_distance_m"] <= 3000
    assert scenario["landuse_manifest"] == str(landuse.resolve())
    assert scenario["landuse_manifest_sha256"] == normalized["sha256"]
    assert scenario["landuse_manifest_file_sha256"] == hashlib.sha256(landuse.read_bytes()).hexdigest()
    assert scenario["landuse"]["join_statistics"]["footprints"] == 11
    assert "Official parcel/group" in scenario["source_note"]
    assert "Synthetic residents, uses" not in scenario["source_note"]


def test_group_weights_use_full_index_before_candidate_limit_and_never_become_capacity(tmp_path):
    manifest, landuse, _normalized = sources(
        tmp_path, centers=[(-500, 25), (500, 25), (1500, 25)], areas=[100, 300, 100],
        rows=[("['0001000', '0001001']", 20, 0), ("0001002", 0, 5000)],
    )
    scenario = build_city_scenario(manifest, 1, landuse_path=landuse, candidate_limit=2)
    home = next(building for building in scenario["buildings"] if building["kind"] == "home")
    evidence = home["land_use"]
    assert evidence["group_footprint_count"] == 2
    assert evidence["residential_units_in_source_group"] == 20
    assert evidence["home_weight"] == {"sf-building:0": 5, "sf-building:1": 15}[home["id"]]
    assert evidence["home_weight"] < 20
    assert home["capacity"] == home["generated_home_resident_count"] == 1
    assert "not source-group dwelling units" in home["capacity_source"]
    assert scenario["landuse"]["join_statistics"]["matched_residential_units_counted_once"] == 20


def test_weighted_home_selection_favors_more_units_within_same_coverage_cell(tmp_path):
    manifest, landuse, _normalized = sources(
        tmp_path, centers=[(100, 25), (200, 25), (1000, 25)],
        rows=[("0001000", 1, 0), ("0001001", 10000, 0), ("0001002", 0, 100)],
    )
    selected = Counter(build_city_scenario(manifest, 1, seed, landuse_path=landuse)["residents"][0]["home_id"]
                       for seed in range(16))
    assert selected["sf-building:1"] >= 15


def test_weighted_work_selection_favors_more_commercial_area(tmp_path):
    manifest, landuse, _normalized = sources(
        tmp_path, centers=[(-500, 25), (500, 25), (600, 25)],
        rows=[("0001000", 1, 0), ("0001001", 0, 1), ("0001002", 0, 10000)],
    )
    selected = Counter(build_city_scenario(manifest, 1, seed, landuse_path=landuse)["residents"][0]["work_id"]
                       for seed in range(16))
    assert selected["sf-building:2"] >= 15


def test_zero_footprint_weight_does_not_qualify_despite_group_eligibility(tmp_path):
    manifest, landuse, _normalized = sources(
        tmp_path, centers=[(-500, 25), (500, 25), (1500, 25)], areas=[0, 100, 100],
        rows=[("['0001000', '0001001']", 20, 0), ("0001002", 0, 5000)],
    )
    scenario = build_city_scenario(manifest, 20, landuse_path=landuse)
    assert {r["home_id"] for r in scenario["residents"]} == {"sf-building:1"}
    assert "sf-building:0" not in {b["id"] for b in scenario["buildings"]}


@pytest.mark.parametrize("rows,missing_role", [
    ([("0001000", 0, 100), ("0001001", 0, 100)], "home"),
    ([("0001000", 10, 0), ("0001001", 10, 0)], "work"),
])
def test_missing_eligible_role_fails_without_inventing_building_uses(tmp_path, rows, missing_role):
    manifest, landuse, _normalized = sources(tmp_path, centers=[(-500, 25), (500, 25)], rows=rows)
    assert build_city_scenario(manifest, 1)["population"] == 1
    with pytest.raises(ValueError, match=f"no positive eligible {missing_role}"):
        build_city_scenario(manifest, 1, landuse_path=landuse)


def test_disconnected_eligible_roles_do_not_fall_back_to_office_homes(tmp_path):
    manifest, landuse, _normalized = sources(
        tmp_path, centers=[(-500, 25), (500, 25), (-500, 4025), (500, 4025)],
        rows=[("0001000", 10, 0), ("0001001", 10, 0), ("0001002", 0, 1000), ("0001003", 0, 1000)],
    )
    assert build_city_scenario(manifest, 20)["population"] == 20
    with pytest.raises(ValueError, match="No eligible residential/commercial walking pair"):
        build_city_scenario(manifest, 20, landuse_path=landuse)


def test_seeded_landuse_prefix_and_repeated_day_population_are_conserved(tmp_path):
    manifest, landuse, _normalized = sources(tmp_path)
    small = build_city_scenario(manifest, 200, 81, landuse_path=landuse)
    large = build_city_scenario(manifest, 1000, 81, landuse_path=landuse)
    assert large["residents"][:200] == small["residents"]
    assert build_city_scenario(manifest, 200, 81, landuse_path=landuse) == small
    model = CivicSimulation(large)
    model.step_ticks((3 * 86_400 + 12 * 3600) * model.tick_hz)
    state = model.snapshot()
    assert state["event_count"] == 16_000
    assert sum(b["occupancy"] for b in state["buildings"]) == 1000
    assert len(state["residents"]) == 1000
    assert large["generation"]["reused_pair_assignments"] > 0


def test_landuse_checksum_is_verified_and_missing_source_is_not_ignored(tmp_path):
    manifest, landuse, _normalized = sources(tmp_path)
    data = json.loads(landuse.read_text())
    data["records"][0]["residential_units"] = 999
    landuse.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        build_city_scenario(manifest, 1, landuse_path=landuse)
    with pytest.raises(FileNotFoundError):
        build_city_scenario(manifest, 1, landuse_path=tmp_path / "missing.json")


def test_landuse_source_metadata_and_generated_counts_survive_detached_save(tmp_path):
    manifest, landuse, _normalized = sources(tmp_path)
    scenario = build_city_scenario(manifest, 20, landuse_path=landuse)
    model = CivicSimulation(scenario)
    model.step_ticks(1200 * model.tick_hz)
    before = model.snapshot()
    altered = model.snapshot()
    altered["buildings"][0]["land_use"]["commercial_by_use_sqft_in_source_group"]["retail"] = -1
    assert model.snapshot() == before
    saved = save_checkpoint(model, tmp_path / "landuse-save.json")
    # The authoritative save carries its scenario. Core reconstruction does not
    # refetch changing source evidence or silently reassign households/jobs.
    landuse.unlink()
    restored = load_checkpoint(saved)
    assert restored.snapshot() == before
    assert restored.scenario["landuse_manifest_sha256"] == scenario["landuse_manifest_sha256"]


def test_distinct_allocations_visit_additional_jobs_without_repeating_pairs(tmp_path):
    centers = [(x, 25) for x in (-1200, -800, -400, 0, 400, 650, 900, 1150, 1400, 1650)]
    rows = [(f"0001{i:03d}", 10 if i < 4 else 0, 0 if i < 4 else 1000) for i in range(len(centers))]
    manifest, landuse, _data = sources(tmp_path, centers=centers, rows=rows)
    ordinary = build_city_scenario(manifest, 20, landuse_path=landuse)
    distinct = build_city_scenario(manifest, 20, landuse_path=landuse, distinct_allocations=True)
    assert ordinary["generation"]["distinct_home_work_pairs"] == 4
    assert distinct["residents"][:4] == ordinary["residents"][:4]
    pairs = {(person["home_id"], person["work_id"]) for person in distinct["residents"]}
    assert len(pairs) == distinct["generation"]["distinct_home_work_pairs"] == 20
    assert distinct["generation"]["reused_pair_assignments"] == 0
    assert distinct["generation"]["route_searches"] <= 4 * 16
    assert distinct["generation"]["generator_version"] == 5
    assert not distinct["generation"]["offline_scale_validation"]
    assert distinct["population_presets"] == list(CITY_POPULATIONS)
    assert build_city_scenario(manifest, 20, landuse_path=landuse, distinct_allocations=True) == distinct
    model = CivicSimulation(distinct)
    model.step_ticks(4 * 86_400 * model.tick_hz)
    assert model.snapshot()["event_count"] == 320
    assert sum(b["occupancy"] for b in model.snapshot()["buildings"]) == 20


def test_distinct_allocations_fail_instead_of_repeating_when_routes_are_insufficient(tmp_path):
    manifest, landuse, _data = sources(
        tmp_path, centers=[(-500, 25), (500, 25)],
        rows=[("0001000", 10, 0), ("0001001", 0, 1000)],
    )
    with pytest.raises(ValueError, match="only 1.*No pair assignments were repeated"):
        build_city_scenario(manifest, 20, landuse_path=landuse, distinct_allocations=True)


def test_offline_two_thousand_distinct_cohort_preserves_live_presets_and_seed_prefix(tmp_path):
    # Many homes share a small set of workplaces, but every building pair is
    # distinct. Sixteen bounded choices per home suffice without all-pairs routes.
    centers = [(-1800 + i * 10, 25) for i in range(150)] + [(300 + i * 35, 25) for i in range(20)]
    rows = [(f"0001{i:03d}", 10 if i < 150 else 0, 0 if i < 150 else 1000) for i in range(len(centers))]
    manifest, landuse, _data = sources(tmp_path, centers=centers, rows=rows)
    small = build_city_scenario(manifest, 200, landuse_path=landuse, distinct_allocations=True)
    large = build_city_scenario(manifest, 2000, landuse_path=landuse, distinct_allocations=True)
    assert len(large["residents"]) == 2000
    assert len({(p["home_id"], p["work_id"]) for p in large["residents"]}) == 2000
    assert large["residents"][:200] == small["residents"]
    assert large["generation"]["offline_scale_validation"]
    assert large["population_presets"] == list(CITY_POPULATIONS) == [1, 20, 200, 1000]
    assert large["generation"]["route_searches"] <= 150 * 16
    buildings = {b["id"]: b for b in large["buildings"]}
    for person in large["residents"]:
        assert buildings[person["home_id"]]["land_use"]["home_weight"] > 0
        assert buildings[person["work_id"]]["land_use"]["work_weight"] > 0
        assert 150 <= person["commute_distance_m"] <= 3000


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_distinct_allocation_option_requires_an_explicit_boolean(tmp_path, value):
    with pytest.raises(ValueError, match="distinct_allocations must be a boolean"):
        build_city_scenario(tmp_path / "missing.json", distinct_allocations=value)
