"""RoboWorld harness interface: plug your own robot brain into RoboWorld.

RoboWorld doesn't ship harnesses; it gives you the robot, the worlds and the
test bench. Your harness subclasses ``Harness`` and drives the robot through
``Robot`` (typed helpers over the robot's MCP tools)::

    from roboworld.harness import Harness, Robot, TaskInfo

    class MyHarness(Harness):
        name = "my-harness"

        async def run(self, robot: Robot, task: TaskInfo) -> None:
            await robot.do("look_around")
            result = await robot.do("walk_to", target="red_ball")
            await robot.finish("walked to the ball", success=result.get("ok"))

Scaffold one with ``rw harness new``, check it with ``rw harness check`` and
compare it with ``rw bench``. See "Building a harness" in the docs.
"""

from roboworld.harness.adapter import HarnessBrain, connect_and_run
from roboworld.harness.core import Harness, Robot, TaskInfo, ToolResult, objects_text

__all__ = ["Harness", "HarnessBrain", "Robot", "TaskInfo", "ToolResult", "connect_and_run", "objects_text"]
