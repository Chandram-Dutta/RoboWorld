"""Phase 5: designing robots: specs, compile, checks, history, tuning, comparisons."""

import pytest

from roboworld import paths
from roboworld.design import api, store
from roboworld.design.spec import RoboSpec, apply_changes, list_templates, load_template
from roboworld.robots import load_manifest, registry


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path / "runs")
    registry.reload()
    yield tmp_path / "library"
    registry.reload()


def test_change_merging():
    base = load_template("duck")
    out = apply_changes(base, {"body.mass": 1.4, "all_legs": {"thigh": 0.1},
                               "legs": {"left_leg": {"foot": [0.12, 0.06]}}, "head": {"neck": 0.03}})
    assert out["body"]["mass"] == 1.4 and out["head"]["neck"] == 0.03
    assert all(leg["thigh"] == 0.1 for leg in out["legs"])
    assert out["legs"][0]["foot"] == [0.12, 0.06] and out["legs"][1]["foot"] == [0.11, 0.05]
    assert base["body"]["mass"] == 1.1  # the template itself is untouched
    with pytest.raises(KeyError, match="no leg named"):
        apply_changes(base, {"legs": {"tail": {"thigh": 0.1}}})


@pytest.mark.parametrize("bad,match", [
    ({"kind": "quadruped"}, "needs 4 legs"),
    ({"all_legs": {"servo": "unobtainium"}}, "unknown servo"),
    ({"name": "Bad Name"}, "pattern"),
])
def test_spec_validation(bad, match):
    data = apply_changes(load_template("duck"), bad)
    data.setdefault("name", "ok_name")
    if "name" not in bad:
        data["name"] = "ok_name"
    with pytest.raises(ValueError, match=match):
        RoboSpec(**data)


@pytest.mark.parametrize("template", sorted(list_templates()))
def test_templates_compile_and_pass_static_checks(library, template):
    out = api.new(f"t_{template}", template, check=False)
    m = load_manifest(out["name"])
    assert m.feet and m.default_gait and m.camera is not None
    report = api.check(out["name"])
    assert report["status"] == "pass", report["summary"]


def test_history_and_safety(library):
    api.new("d1", "mini_dog", check=False)
    api.derive("d1", "d2", {"all_legs.thigh": 0.1}, note="longer thighs", check=False)
    api.derive("d2", "d3", "body: {mass: 0.8}", note="lighter", check=False)
    chain = api.history("d3")
    assert [h["name"] for h in chain] == ["d3", "d2", "d1"] and chain[0]["note"] == "lighter"
    assert store.load("d3").spec.legs[0].thigh == 0.1
    assert {d["name"] for d in api.designs()} == {"d1", "d2", "d3"}
    with pytest.raises(FileExistsError):
        api.new("d1", "duck", check=False)
    with pytest.raises(ValueError, match="built-in"):
        api.new("go2", "mini_dog", check=False)


def test_designed_robot_runs_skills_in_a_task(library):
    from roboworld.episode import Episode

    api.new("dog", "mini_dog", check=False)
    ep = Episode("dog", "find_red_ball", record=False)
    ep.do("look_around")
    r = ep.do("walk_to", {"target": "red_ball"})
    assert r["ok"] and ep.success
    ep.close()


def test_compare_same_brain_different_bodies(library):
    api.new("dog", "mini_dog", check=False)
    out = api.compare(["dog", "go2"], ["find_red_ball"], seeds=1, parallel=2)
    assert set(out["robots"]) == {"dog", "go2"}
    assert out["robots"]["dog"]["tasks"]["find_red_ball"] == "1/1"


def test_tune_saves_an_improved_child(library):
    api.new("hx", "hexapod", check=False)
    out = api.tune("hx", course="flat", trials=4)
    assert out["trials"] == 4 and out["best_score_m"] >= out["baseline_score_m"]
    if "saved_as" in out:
        assert store.load(out["saved_as"]).meta["parent"] == "hx"
