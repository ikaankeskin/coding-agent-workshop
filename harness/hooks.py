"""Shell hooks that run outside the model. Only their output can enter the context."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path

from harness.config import HookSpec

HOOK_TIMEOUT = 30
HOOK_OUTPUT_LIMIT = 20_000


@dataclass
class HookRun:
    blocked: bool
    output: str


class Hooks:
    def __init__(self, pre_tool: list[HookSpec], post_tool: list[HookSpec], stop_hooks: list[HookSpec], workspace: Path):
        self.pre_tool = pre_tool
        self.post_tool = post_tool
        self.stop_hooks = stop_hooks
        self.workspace = workspace

    def run_pre(self, tool_name: str) -> HookRun:
        return self._run(self.pre_tool, tool_name, block_on_failure=True)

    def run_post(self, tool_name: str) -> HookRun:
        return self._run(self.post_tool, tool_name, block_on_failure=False)

    def run_stop(self) -> None:
        self._run(self.stop_hooks, tool_name=None, block_on_failure=False)

    def _run(self, specs: list[HookSpec], tool_name: str | None, block_on_failure: bool) -> HookRun:
        chunks: list[str] = []
        for spec in specs:
            if spec.tool and spec.tool != tool_name:
                continue
            try:
                completed = subprocess.run(
                    spec.command,
                    shell=True,
                    cwd=self.workspace,
                    capture_output=True,
                    text=True,
                    timeout=HOOK_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                text = "hook timed out"
                if block_on_failure:
                    return HookRun(True, text)
                chunks.append(text)
                continue
            text = _clip((completed.stdout or "") + (completed.stderr or ""))
            if completed.returncode != 0 and block_on_failure:
                return HookRun(True, text or f"hook exited {completed.returncode}")
            if text:
                chunks.append(text)
        return HookRun(False, "\n".join(chunks))


def _clip(text: str) -> str:
    if len(text) <= HOOK_OUTPUT_LIMIT:
        return text.strip()
    return text[:HOOK_OUTPUT_LIMIT] + "\n...[truncated]"
