"""Command line entry point."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from harness.appa import AppaClient, AppaSession
from harness.config import load_settings
from harness.decisions import Decisions, OpenJevClient
from harness.errors import ConfigError, HarnessError
from harness.loop import run
from harness.providers import Providers
from harness.providers.anthropic import AnthropicProvider
from harness.providers.openai import OpenAIProvider
from harness.routing import Router
from harness.trace import Trace, TracingClient


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    dev, ui, port, args = _parse(list(sys.argv[1:] if argv is None else argv))
    workspace = Path.cwd()
    try:
        settings = load_settings(workspace)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not settings.models:
        print(_missing_catalog(), file=sys.stderr)
        return 2
    if ui:
        from harness.ui import serve

        serve(lambda task, trace, options=None: _ui_task(workspace, settings, task, trace, options or {}), str(workspace), port)
        return 0
    if args:
        task = " ".join(args).strip()
        if not task:
            print("Give a task as arguments, or type one and finish with an empty line.", file=sys.stderr)
            return 2
        return _run_task(workspace, settings, task, dev=dev)
    print("Type a task, then a blank line. quit exits.", file=sys.stderr, flush=True)
    while True:
        task = _read_interactive()
        if task is None:
            return 0
        if not task:
            continue
        _run_task(workspace, settings, task, dev=dev)
        print(file=sys.stderr)


def _parse(argv: list[str]) -> tuple[bool, bool, int, list[str]]:
    dev = False
    ui = False
    port = 8765
    rest: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--dev":
            dev = True
        elif arg == "--ui":
            ui = True
        elif arg == "--port" and index + 1 < len(argv):
            index += 1
            port = int(argv[index])
        elif arg in ("-h", "--help"):
            print(_help())
            raise SystemExit(0)
        else:
            rest.append(arg)
        index += 1
    return dev, ui, port, rest


def _run_task(
    workspace: Path,
    settings,
    task: str,
    *,
    dev: bool = False,
    trace: Trace | None = None,
    echo: bool = True,
    anthropic_api_key: str | None = None,
    openappa: bool | None = None,
    appa_url: str | None = None,
) -> int:
    trace = trace or Trace(dev=dev)
    decisions = Decisions(
        TracingClient(
            OpenJevClient(
                settings.openjev_base_url,
                settings.openjev_model,
                api_key=os.environ.get("OPENJEV_API_KEY"),
            ),
            trace,
        ),
        settings.confidence_min,
    )
    providers = Providers({"openai": OpenAIProvider(), "anthropic": AnthropicProvider(api_key=anthropic_api_key or None)})
    try:
        result = run(
            task,
            workspace=workspace,
            settings=settings,
            providers=providers,
            decisions=decisions,
            router=Router(settings, decisions, trace=trace),
            on_text=_write_chunk,
            echo=echo,
            trace=trace,
            appa=_appa_session(openappa, appa_url),
        )
    except HarnessError as exc:
        print(exc, file=sys.stderr)
        return 1
    if echo and result.text and not result.text.endswith("\n"):
        print(file=sys.stdout)
    if result.reason in ("context_limit", "no_model"):
        print(result.reason, file=sys.stderr)
        return 1
    return 0


def _ui_task(workspace: Path, settings, task: str, trace: Trace, options: dict) -> int:
    key = str(options.get("anthropic_api_key") or "").strip() or None
    return _run_task(
        workspace,
        settings,
        task,
        trace=trace,
        echo=False,
        anthropic_api_key=key,
        openappa=bool(options.get("openappa")),
        appa_url=str(options.get("appa_url") or "").strip() or None,
    )


def _appa_session(openappa: bool | None = None, appa_url: str | None = None) -> AppaSession | None:
    """The command line follows APPA_RUNTIME_URL. The page follows its toggle."""
    if openappa is False:
        return None
    url = (appa_url or os.environ.get("APPA_RUNTIME_URL", "")).strip()
    if openappa is None and not url:
        return None
    if openappa and not url:
        url = "http://127.0.0.1:8787"
    if not url:
        return None
    return AppaSession(AppaClient(url))


def _read_interactive() -> str | None:
    lines: list[str] = []
    first = True
    while True:
        try:
            if first:
                print("task> ", end="", file=sys.stderr, flush=True)
            line = input()
        except EOFError:
            return None
        first = False
        if line == "":
            break
        if not lines and line.strip().lower() in {"quit", "exit"}:
            return None
        lines.append(line)
    return "\n".join(lines).strip()


def _load_dotenv() -> None:
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"]
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _write_chunk(chunk: str) -> None:
    sys.stdout.write(chunk)
    sys.stdout.flush()


def _help() -> str:
    return (
        "Usage: python -m harness [--dev] [--ui] [--port 8765] [task]\n"
        "  --dev   print each backend step: route, OpenJev, context, tools, hooks, stop\n"
        "  Set APPA_RUNTIME_URL to check sub-agents with a local OpenAPPA runtime.\n"
        "  --ui    open a local page that shows the loop and the same log\n"
    )


def _missing_catalog() -> str:
    return (
        "No models configured. Add a catalog to .agent/settings.json "
        "or ~/.agent-harness/settings.json. Each entry needs id, provider "
        "(\"openai\" or \"anthropic\"), model, context_limit, and notes. "
        "Set default_model to one of those ids."
    )


if __name__ == "__main__":
    raise SystemExit(main())
