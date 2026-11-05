"""Phase 4: the harness interface: plugging in your own harness and testing it."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import textwrap
import time

import pytest
from typer.testing import CliRunner

from roboworld import paths
from roboworld.brain import registry, runner
from roboworld.brain.baseline import KeywordHarness
from roboworld.harness import HarnessBrain, connect_and_run


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path)
    return tmp_path


def test_harness_plugs_in_from_a_file(runs_dir, tmp_path):
    f = tmp_path / "mine.py"
    f.write_text(textwrap.dedent('''
        from roboworld.harness import Harness

        class Mine(Harness):
            name = "mine"

            def __init__(self, threshold=1):
                super().__init__()
                self.threshold = threshold

            async def run(self, robot, task):
                await robot.do("look_around")
                r = await robot.do("walk_to", target="red_ball")
                self.stats.update(custom_metric=42, threshold=self.threshold, cost_usd=0.01)
                await robot.finish("done", success=r.get("ok"))
    '''))
    spec = tmp_path / "mine.yaml"
    spec.write_text(f"type: harness\nharness: {f}:Mine\nparams: {{threshold: 7}}\n")
    result = runner.run_episode("go2", "find_red_ball", registry.resolve(str(spec)), record=False)
    assert result["success"] and result["brain"] == "mine"
    stats = result["brain_stats"]["llm"]
    assert stats["custom_metric"] == 42 and stats["threshold"] == 7 and stats["harness"] == "mine"


def test_installed_entry_point_harness(monkeypatch):
    class Installed:
        name = "installed-ep"
        value = "some_package.harness:KeywordHarness"

        def load(self):
            return KeywordHarness

    monkeypatch.setattr(registry, "entry_points", lambda: {"installed-ep": Installed()})
    brain = registry.resolve("installed-ep")
    assert isinstance(brain, HarnessBrain) and brain.name == "installed-ep"
    assert any(b["name"] == "installed-ep" for b in registry.list_brains())


def test_example_llm_harness_with_a_fake_model(runs_dir, monkeypatch):
    sys.path.insert(0, str(paths.HOME))
    brain = registry.resolve(str(paths.HOME / "examples/harnesses/llm_harness.yaml"))
    module = sys.modules[type(brain.harness).__module__]
    replies = iter(['{"skill": "look_around", "args": {}}', '{"skill": "walk_to", "args": {"target": "red_ball"}}'])

    async def fake_ask(prompt, image=None):
        assert image and image[:4] == b"\x89PNG" and "Task:" in prompt
        return next(replies, '{"done": true, "success": true}')

    monkeypatch.setattr(module, "ask", fake_ask)
    result = runner.run_episode("go2", "find_red_ball", brain, record=False)
    assert result["success"] and result["brain_stats"]["llm"]["llm_calls"] == 2


def test_scaffold_and_check(tmp_path, monkeypatch):
    from roboworld.cli import app

    monkeypatch.setenv("ROBOWORLD_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path / "runs")
    cli = CliRunner()
    made = cli.invoke(app, ["harness", "new", "My Thing", "--dir", str(tmp_path / "h")])
    assert made.exit_code == 0, made.output
    assert (tmp_path / "h" / "my_thing.py").exists() and (tmp_path / "h" / "my_thing.yaml").exists()
    checked = cli.invoke(app, ["harness", "check", str(tmp_path / "h" / "my_thing.yaml")])
    assert checked.exit_code == 0 and "OK: harness ran cleanly" in checked.output, checked.output


def test_connect_and_run_against_a_live_http_server(runs_dir):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "ROBOWORLD_RUNS_DIR": str(runs_dir)}
    proc = subprocess.Popen([sys.executable, "-m", "roboworld.cli", "serve-robot", "--robot", "go2", "--task",
                             "find_red_ball", "--run-id", "http-run", "--no-record", "--http", str(port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        robot = asyncio.run(connect_and_run(KeywordHarness(), url=f"http://127.0.0.1:{port}/mcp"))
        assert robot.finished
        assert json.loads((runs_dir / "http-run" / "result.json").read_text())["success"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_walk_to_a_point_arrives_at_it(runs_dir):
    from roboworld.episode import Episode

    ep = Episode("go2", "avoid_red_zone", record=False)
    r = ep.do("walk_to", {"target": [-0.5, 1.0]})
    assert r["ok"] and r["distance_m"] <= 0.1
    ep.close()
