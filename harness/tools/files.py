"""Read, edit, and write files. Edits use an exact old/new pair and require a fresh read."""

from __future__ import annotations

from harness.messages import ToolResult
from harness.tools.common import Tool, ToolContext, display, resolve_target, snapshot

DEFAULT_READ_LIMIT = 400


def read_file(arguments: dict, ctx: ToolContext) -> ToolResult:
    path, error = resolve_target(ctx.workspace, arguments.get("path", ""))
    if error:
        return error
    assert path is not None
    if not path.is_file():
        return ToolResult(False, f"{path.name} is not a file", "not_found")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(False, "file is not valid UTF-8", "binary")
    if "\0" in text:
        return ToolResult(False, "file looks binary", "binary")
    lines = text.splitlines()
    offset = _int(arguments.get("offset"), 1)
    limit = _int(arguments.get("limit"), DEFAULT_READ_LIMIT)
    if offset < 1 or limit < 1:
        return ToolResult(False, "offset and limit must be positive", "invalid_arguments")
    if lines and offset > len(lines):
        return ToolResult(False, f"offset {offset} is past the end ({len(lines)} lines)", "past_end")
    ctx.reads[str(path)] = snapshot(path)
    selected = lines[offset - 1 : offset - 1 + limit]
    end = offset - 1 + len(selected)
    numbered = "\n".join(f"{offset + index}|{line}" for index, line in enumerate(selected))
    header = f"{display(ctx.workspace, path)} lines {offset}-{end} of {len(lines)}"
    if end < len(lines):
        header += f". More lines remain; read again with offset {end + 1}."
    body = f"{header}\n{numbered}" if numbered else header
    return ToolResult(True, body)


def edit_file(arguments: dict, ctx: ToolContext) -> ToolResult:
    path, error = resolve_target(ctx.workspace, arguments.get("path", ""))
    if error:
        return error
    assert path is not None
    old = arguments.get("old_string")
    new = arguments.get("new_string")
    if not isinstance(old, str) or old == "":
        return ToolResult(False, "old_string is required", "invalid_arguments")
    if not isinstance(new, str):
        return ToolResult(False, "new_string is required", "invalid_arguments")
    key = str(path)
    if key not in ctx.reads:
        return ToolResult(False, "Read the file before editing it.", "not_read")
    if not path.is_file():
        return ToolResult(False, "file does not exist", "not_found")
    if snapshot(path) != ctx.reads[key]:
        return ToolResult(False, "The file changed since it was read. Read it again before editing.", "stale")
    content = path.read_text(encoding="utf-8")
    count = content.count(old)
    if count == 0:
        return ToolResult(False, "old_string was not found.", "not_found")
    if count > 1:
        return ToolResult(False, "old_string matched more than once. Include more surrounding context.", "ambiguous")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    ctx.reads[key] = snapshot(path)
    return ToolResult(True, f"Edited {display(ctx.workspace, path)}")


def write_file(arguments: dict, ctx: ToolContext) -> ToolResult:
    path, error = resolve_target(ctx.workspace, arguments.get("path", ""))
    if error:
        return error
    assert path is not None
    content = arguments.get("content")
    if not isinstance(content, str):
        return ToolResult(False, "content is required", "invalid_arguments")
    if path.exists() and str(path) not in ctx.reads:
        return ToolResult(False, "Read the file before overwriting it.", "not_read")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ctx.reads[str(path)] = snapshot(path)
    return ToolResult(True, f"Wrote {display(ctx.workspace, path)}")


def _int(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def file_tools() -> list[Tool]:
    return [
        Tool(
            "read_file",
            "Read a UTF-8 text file. Large files are paged. offset is a 1-based line number.",
            {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            ["path"],
            read_file,
        ),
        Tool(
            "edit_file",
            "Replace one exact old_string with new_string. The file must have been read first and must be unchanged since that read.",
            {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            ["path", "old_string", "new_string"],
            edit_file,
        ),
        Tool(
            "write_file",
            "Create a file or replace its whole contents. An existing file must have been read first.",
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            ["path", "content"],
            write_file,
        ),
    ]
