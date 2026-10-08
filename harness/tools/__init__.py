"""The tool registry built at startup. Extra tools can be added before the loop runs."""

from __future__ import annotations

from harness.tools.bash import bash_tool
from harness.tools.common import Registry, Tool
from harness.tools.files import file_tools
from harness.tools.notes import note_tool
from harness.tools.search import search_tools
from harness.tools.spawn import spawn_tool


def build_registry(extra: list[Tool] | None = None) -> Registry:
    registry = Registry([*file_tools(), bash_tool(), *search_tools(), note_tool(), spawn_tool()])
    for tool in extra or []:
        registry.add(tool)
    return registry
