"""Phase 3: randomised worlds, richer success rules, walls, the benchmark and plug-in harnesses."""

import json
import textwrap

import pytest

from roboworld import paths
from roboworld.bench import run_bench
from roboworld.brain import registry, runner
from roboworld.episode import Episode
from roboworld.world.spec import TaskSpec, WorldSpec, list_tasks, load_world


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path)
    return tmp_path


def test_every_task_loads_and_has_a_world():
    names = {t.name for t in list_tasks()}
    assert len(names) >= 8
    for t in list_tasks():
        assert t.resolved_world().objects


def test_random_placement_is_per_seed_and_repeatable():
    w = load_world("ball_room")
    a, b, a2 = w.resolved(0), w.resolved(1), w.resolved(0)
    pos = lambda world: [o.pos for o in world.objects]  # noqa: E731
    assert pos(a) == pos(a2) and pos(a) != pos(b)
    for o in a.objects:
        if o.place_in:
            (x0, x1), (y0, y1) = o.place_in
            assert x0 <= o.pos[0] <= x1 and y0 <= o.pos[1] <= y1


def test_walls_are_seen_as_segments(runs_dir):
    ep = Episode("go2", "push_ball_to_goal", record=False)
    ep.do("look_around")
    walls = {k: v for k, v in ep.perception.memory.items() if v.kind == "wall"}
    assert set(walls) == {"wall_east", "wall_west", "wall_north", "wall_south"}
    assert walls["wall_east"].segment[0][0] == pytest.approx(2.0)
    ep.close()


def test_sequence_must_happen_in_order(runs_dir):
    ep = Episode("go2", "visit_crate_then_ball", record=False)
    ep.do("look_around")
    ep.do("walk_to", {"target": "red_ball"})
    assert not ep.success  # ball first doesn't count
    ep.do("walk_to", {"target": "blue_crate"})
    ep.do("walk_to", {"target": "red_ball"})
    assert ep.success
    ep.close()


@pytest.mark.parametrize("answer,ok", [("three", True), ("3", True), ("2", False)])
def test_answer_is_checked(runs_dir, answer, ok):
    ep = Episode("go2", "count_red_balls", record=False)
    ep.finish("counted", answer=answer)
    assert ep.success is ok


def test_breaking_a_rule_fails_the_task(runs_dir):
    ep = Episode("go2", "avoid_red_zone", record=False)
    ep.do("look_around")
    r = ep.do("walk_to", {"target": "green_area"})  # straight through the red zone
    assert "rule of the task was broken" in r["message"]
    assert ep.close()["status"] == "failed"


def test_push_explains_when_a_wall_is_in_the_way(runs_dir):
    world = WorldSpec(name="t", walls={"half_size": [2.0, 2.0]}, robot_start={"pos": [0.3, 0.6]}, objects=[
        {"name": "red_ball", "shape": "sphere", "size": [0.13], "pos": [1.8, 0.2], "color": "red"},
        {"name": "green_goal", "shape": "region", "size": [0.3, 0.3], "pos": [0.6, -1.1], "color": "green"}])
    task = TaskSpec(name="t", instruction="push", world=world,
                    success={"object_in_region": {"object": "red_ball", "region": "green_goal"}})
    ep = Episode("go2", task, record=False)
    ep.do("look_around")
    r = ep.do("push", {"object": "red_ball", "to": "green_goal"})
    assert not r["ok"] and "too close to wall_east" in r["message"]
    ep.close()


def test_bench_writes_report(runs_dir):
    out = run_bench(["go2"], ["find_red_ball", "count_red_balls"], ["baseline"], seeds=1, parallel=2, name="t")
    assert out["by_brain"]["baseline:keyword"]["successes"] == 2
    bench_dir = runs_dir / out["bench_id"]
    for name in ("results.csv", "summary.json", "report.html"):
        assert (bench_dir / name).exists()
    assert "Leaderboard" in (bench_dir / "report.html").read_text()


def test_plugin_harness_and_overclaim(runs_dir, tmp_path):
    harness = tmp_path / "liar.py"
    harness.write_text(textwrap.dedent('''
        from dataclasses import dataclass, field
        from roboworld.brain.brains import call_tool

        @dataclass
        class Liar:
            name: str = "liar"
            stats: dict = field(default_factory=dict)
            log: list = field(default_factory=list)

            async def run(self, session, instructions, prompt, tools, max_turns):
                await call_tool(session, "look", {})
                await call_tool(session, "finish", {"summary": "done!", "success": True})
    '''))
    spec = tmp_path / "liar.yaml"
    spec.write_text(f"name: liar\ntype: python\nentry: {harness}:Liar\n")
    brain = registry.resolve(str(spec))
    assert brain.name == "liar"
    result = runner.run_episode("go2", "find_red_ball", brain, run_id="liar-run")
    stats = result["brain_stats"]
    assert not result["success"] and stats["claimed_success"] is True and stats["overclaimed"] is True
    assert json.loads((runs_dir / "liar-run" / "result.json").read_text())["brain"] == "liar"


def test_unknown_brain_lists_options():
    with pytest.raises(KeyError, match="baseline"):
        registry.resolve("definitely-not-a-brain")
