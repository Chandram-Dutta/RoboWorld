"""Phase 2: episodes, honest perception, skills, the robot MCP server and brains."""

import json
import shutil
import time

import httpx
import pytest

from roboworld import paths
from roboworld.brain import brains, runner
from roboworld.episode import Episode


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS_DIR", tmp_path)
    return tmp_path


def test_perception_is_honest(runs_dir):
    ep = Episode("go2", "find_red_ball", record=False)
    # The ball is behind the robot: it can't walk to something it hasn't seen.
    r = ep.do("walk_to", {"target": "red_ball"})
    assert not r["ok"] and "haven't seen" in r["message"]
    names = {o["name"] for o in ep.observe()["objects_seen"]}
    assert "red_ball" not in names
    r = ep.do("look_around")
    assert r["ok"] and any(o["name"] == "red_ball" for o in r["objects"])
    ep.close()


def test_go2_finds_ball(runs_dir):
    ep = Episode("go2", "find_red_ball", record=False)
    ep.do("look_around")
    r = ep.do("walk_to", {"target": "red ball"})
    assert r["episode"]["over"] and ep.success
    res = ep.close()
    assert res["status"] == "success" and res["progress"] == 1.0
    assert res["brain_stats"]["skills_used"] == {"look_around": 1, "walk_to": 1}


def test_duck_pushes_ball_into_goal(runs_dir):
    ep = Episode("open_duck_mini_v2", "push_ball_to_goal", record=False)
    ep.look()
    r = ep.do("push", {"object": "red_ball", "to": "green_goal"})
    assert r["ok"], r
    assert ep.close()["success"]


def test_invalid_calls_are_reported_not_raised(runs_dir):
    ep = Episode("go2", "find_red_ball", record=False)
    assert "unknown skill" in ep.do("fly")["error"]
    assert "bad args" in ep.do("turn", {"degrees": "lots"})["error"]
    assert ep.run("do: [{pose: nope}]")["errors"]
    assert ep.close()["brain_stats"]["invalid_calls"] == 3


def test_realtime_mode_spends_thinking_time(runs_dir):
    ep = Episode("go2", "find_red_ball", mode="realtime", record=False)
    t0 = ep.observe()["episode"]["time_s"]
    time.sleep(0.6)  # the brain "thinks"
    t1 = ep.observe()["episode"]["time_s"]
    assert t1 - t0 == pytest.approx(0.6, abs=0.15)
    paused = Episode("go2", "find_red_ball", mode="paused", record=False)
    p0 = paused.observe()["episode"]["time_s"]
    time.sleep(0.3)
    assert paused.observe()["episode"]["time_s"] == p0
    ep.close()
    paused.close()


def test_skills_in_robolang_programs(runs_dir):
    ep = Episode("go2", "find_red_ball", record=False)
    r = ep.run("""
do:
  - skill: turn
    args: {degrees: 90}
  - skill: walk
    args: {distance: 0.3}
""")
    assert r["ok"], r
    assert 75 < r["robot"]["heading_deg"] < 110
    ep.close()


def test_scripted_brain_over_mcp(runs_dir, tmp_path):
    script = [{"look": {}}, {"do": {"skill": "look_around"}}, {"do": {"skill": "walk_to", "args": {"target": "red_ball"}}}]
    result = runner.run_episode("go2", "find_red_ball", brains.ScriptedBrain(name="scripted", steps=script),
                                run_id="t-scripted")
    assert result["success"], result
    assert (runs_dir / "t-scripted" / "transcript.jsonl").exists()


def fake_llm(plan):
    """An OpenAI-compatible endpoint whose 'model' follows a fixed plan of tool calls."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.url.path.endswith("/chat/completions")
        assert {t["function"]["name"] for t in body["tools"]} >= {"observe", "look", "do", "finish"}
        turn = sum(1 for m in body["messages"] if m["role"] == "assistant")
        if turn >= len(plan):
            msg = {"role": "assistant", "content": "done"}
        else:
            name, args = plan[turn]
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{turn}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
        return httpx.Response(200, json={"choices": [{"message": msg}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 10}})

    return httpx.MockTransport(handler), seen


def test_openai_compatible_brain_over_mcp(runs_dir):
    plan = [("look", {}), ("do", {"skill": "look_around"}),
            ("do", {"skill": "walk_to", "args": {"target": "red_ball"}}), ("finish", {"summary": "found it"})]
    transport, seen = fake_llm(plan)
    brain = brains.OpenAICompatBrain(base_url="http://fake/v1", model="fake-model", transport=transport)
    result = runner.run_episode("go2", "find_red_ball", brain, run_id="t-openai")
    assert result["success"], result
    llm = result["brain_stats"]["llm"]
    assert llm["llm_calls"] >= 3 and llm["prompt_tokens"] >= 300
    # After look(), the camera image was sent to the model as an image part.
    image_msgs = [m for m in seen[1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)]
    assert image_msgs and image_msgs[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    # Tool results went back as role=tool messages.
    assert any(m["role"] == "tool" for m in seen[-1]["messages"])


def test_mcp_config_is_client_agnostic():
    cfg = runner.mcp_config("go2", "find_red_ball", "paused", 0, "x", "any")
    server = cfg["mcpServers"]["robot"]
    assert "serve-robot" in server["args"] and server["command"]
    shutil.rmtree(paths.RUNS_DIR / "x", ignore_errors=True)


def test_saved_motion_becomes_playable(runs_dir, tmp_path, monkeypatch):
    from roboworld import api

    monkeypatch.setattr(paths, "LIBRARY_DIR", tmp_path / "library")
    out = api.save_motion("go2", "sit_up", "do: [{pose: crouch, duration: 0.5}, {pose: home, duration: 0.5}]",
                          "crouch then stand")
    assert out["ok"], out
    assert api.save_motion("go2", "Bad Name", "do: [{wait: 1}]")["ok"] is False
    assert api.save_motion("go2", "broken", "do: [{pose: nope}]")["ok"] is False
    ep = Episode("go2", "find_red_ball", record=False)
    assert {"name": "sit_up", "description": "crouch then stand"} in ep.skills()["saved_motions"]
    r = ep.do("play", {"motion": "sit_up"})
    assert r["ok"] and r["message"] == "played sit_up"
    ep.close()


def test_codex_flags_register_only_the_robot_server():
    cfg = runner.mcp_config("go2", "find_red_ball", "paused", 0, "y", "codex")
    flags = runner.codex_flags(cfg)
    for key in ("command=", "args=[", "env={", "tool_timeout_sec=", 'default_tools_approval_mode="approve"'):
        assert f"mcp_servers.robot.{key}" in flags
    assert "codex exec" in runner.PRESETS["codex"] and "{codex_flags}" in runner.PRESETS["codex"]
    shutil.rmtree(paths.RUNS_DIR / "y", ignore_errors=True)
