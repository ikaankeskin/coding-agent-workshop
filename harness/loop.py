"""The agent loop: stream a turn, run tools, compress, and stop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys

from harness.config import Settings
from harness.context import (
    Context,
    over_budget,
    rewrite_instructions,
    summary_instructions,
    summary_too_long,
)
from harness.decisions import Decisions, Permit
from harness.appa import AppaSession
from harness.errors import ContextLimitError, NoModelError
from harness.hooks import Hooks
from harness.messages import Message, ToolCall, ToolResult, format_tool_result, render_transcript
from harness.providers import Providers
from harness.routing import Router
from harness.tools import build_registry
from harness.tools.common import Registry, ToolContext
from harness.trace import Trace

SYSTEM_PROMPT = """You are a coding agent. You can read files, edit files, write files, run shell commands, search with grep and glob, write notes, and spawn a sub-agent for a large investigation.

Use edit_file with the exact old text and the new text. Read a file before you edit or overwrite it. Prefer edit_file over rewriting a whole file. After a session is compressed, read a file again before editing it.

When the task is finished, reply with no tool calls.
"""

CONTINUATION = "The task is not finished. Continue until it is done."


@dataclass
class RunResult:
    text: str
    reason: str
    messages: list[Message] = field(default_factory=list)


@dataclass
class Session:
    workspace: Path
    settings: Settings
    context: Context
    reads: dict[str, tuple[int, int]]
    registry: Registry
    decisions: Decisions
    router: Router
    providers: Providers
    hooks: Hooks
    task: str
    scope: str
    depth: int
    on_text: object
    echo: bool
    trace: Trace
    appa: AppaSession | None = None
    appa_child: str | None = None
    current_call: ToolCall | None = None


def run(
    task: str,
    *,
    workspace: Path,
    settings: Settings,
    providers: Providers,
    decisions: Decisions,
    router: Router | None = None,
    registry: Registry | None = None,
    on_text=None,
    echo: bool = False,
    depth: int = 0,
    scope: str | None = None,
    trace: Trace | None = None,
    appa: AppaSession | None = None,
    appa_child: str | None = None,
) -> RunResult:
    workspace = workspace.resolve()
    router = router or Router(settings, decisions)
    registry = registry or build_registry()
    if depth > 0:
        registry = registry.without("spawn_agent")
    system = _system_prompt(workspace)
    session = Session(
        workspace=workspace,
        settings=settings,
        context=Context(system),
        reads={},
        registry=registry,
        decisions=decisions,
        router=router,
        providers=providers,
        hooks=Hooks(settings.pre_tool, settings.post_tool, settings.stop_hooks, workspace),
        task=task,
        scope=scope or ("main" if depth == 0 else "subagent"),
        depth=depth,
        on_text=on_text or (lambda _chunk: None),
        echo=echo,
        trace=trace or Trace(),
        appa=appa,
        appa_child=appa_child,
    )
    if appa is not None and depth == 0:
        appa.start(task)
    _trace(session, "user", task, stage="user")
    session.context.add(Message("user", task))
    reason = "turn_limit"
    nudged = False
    turns = 0
    max_turns = _turn_cap(settings, depth)
    try:
        while turns < max_turns:
            try:
                model = _prepare(session)
            except (ContextLimitError, NoModelError) as exc:
                reason = "context_limit" if isinstance(exc, ContextLimitError) else "no_model"
                _echo(session, str(exc))
                break
            sent = len(session.context.transcript)
            _echo(session, f"model: {model.id} ({model.provider}/{model.model})")
            _trace(
                session,
                "model",
                f"turn {turns + 1} {model.id} ({model.provider}/{model.model})",
                stage="model",
                catalog_id=model.id,
                provider=model.provider,
                model=model.model,
                turn=turns + 1,
            )
            completion = session.providers.stream(
                model,
                session.context.messages(),
                session.registry.schemas(),
                lambda chunk: _stream_text(session, chunk),
            )
            session.context.note_usage(completion.input_tokens, sent)
            session.context.add(completion.message)
            turns += 1
            calls = completion.message.tool_calls or []
            if not calls:
                if nudged or _finished(session, completion.message.content or ""):
                    reason = "completed"
                    break
                nudged = True
                _trace(session, "openjev", "task is not finished; the model gets one continuation", stage="openjev")
                session.context.add(Message("user", CONTINUATION))
                continue
            nudged = False
            _run_tools(session, calls)
        else:
            reason = "turn_limit"
    except KeyboardInterrupt:
        reason = "interrupted"
    finally:
        if session.settings.stop_hooks:
            _trace(session, "hooks", "stop hooks", stage="hooks")
        session.hooks.run_stop()
    _trace(session, "stop", reason, stage="stop", reason=reason)
    return RunResult(_last_assistant_text(session.context.messages()), reason, session.context.messages())


def _prepare(session: Session):
    estimate = session.context.estimate()
    model = session.router.sticky(session.scope)
    model_limit = model.context_limit if model is not None else None
    ceiling = session.settings.context_limit if model_limit is None else min(session.settings.context_limit, model_limit)
    _trace(
        session,
        "context",
        f"{estimate} tokens, budget {ceiling}",
        stage="context",
        estimate=estimate,
        budget=ceiling,
    )
    if over_budget(
        estimate,
        context_limit=session.settings.context_limit,
        model_limit=model_limit,
        reply_reserve=session.settings.reply_reserve,
    ):
        _trace(session, "compress", f"context reached the budget ({estimate} tokens)", stage="context", estimate=estimate)
        if not _compress(session):
            raise ContextLimitError("Compression could not bring the context under the limit.")
        estimate = session.context.estimate()
        model = session.router.sticky(session.scope)
        if model is not None and not session.router.fits(model, estimate):
            model = None
    if model is None or not session.router.fits(model, estimate):
        model = session.router.choose(
            kind="subagent" if session.depth else "main",
            scope=session.scope,
            task=session.task,
            token_estimate=estimate,
            refit=session.router.sticky(session.scope) is not None,
        )
    if over_budget(
        session.context.estimate(),
        context_limit=session.settings.context_limit,
        model_limit=model.context_limit,
        reply_reserve=session.settings.reply_reserve,
    ):
        raise ContextLimitError("The context is still over the limit after compression.")
    return model


def _compress(session: Session) -> bool:
    estimate = session.context.estimate()
    try:
        entry = session.router.choose(
            kind="compress",
            scope=f"{session.scope}:compress",
            task=session.task,
            token_estimate=estimate,
            refit=True,
            remember=False,
        )
    except NoModelError:
        return False
    transcript = render_transcript(session.context.messages())
    draft = _complete(
        session,
        entry,
        [Message("system", summary_instructions()), Message("user", transcript)],
    )
    if summary_too_long(draft, session.settings.summary_token_cap):
        draft = _complete(
            session,
            entry,
            [Message("system", rewrite_instructions()), Message("user", draft)],
        )
        if summary_too_long(draft, session.settings.summary_token_cap):
            return False
    if not draft.strip():
        return False
    session.context.replace_transcript(draft)
    session.reads.clear()
    if session.context.estimate() > session.settings.context_limit:
        return False
    _echo(session, "context compressed")
    _trace(
        session,
        "compress",
        "transcript replaced with the summary; read tracker cleared",
        stage="context",
        summary_tokens=session.context.estimate(),
    )
    return True


def _complete(session: Session, entry, messages: list[Message]) -> str:
    completion = session.providers.stream(entry, messages, [], lambda _chunk: None)
    return completion.message.content or ""


def _run_tools(session: Session, calls: list[ToolCall]) -> None:
    ctx = ToolContext(
        workspace=session.workspace,
        reads=session.reads,
        depth=session.depth,
        user_task=session.task,
        decisions=session.decisions,
        spawn=lambda task: _spawn(session, task),
    )
    for call in calls:
        _echo(session, f"tool: {call.name}")
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        _trace(session, "tool", f"{call.name} {arguments}", stage="tools", tool=call.name, arguments=arguments)
        allowed = _authorize(session, call)
        decision = "allow" if allowed.allowed else "deny"
        _trace(
            session,
            "permit",
            f"{decision} {call.name}: {allowed.reason or 'allowed'}",
            stage="tools",
            tool=call.name,
            allowed=allowed.allowed,
            reason=allowed.reason,
        )
        if not allowed.allowed:
            session.context.add(_tool_message(call, ToolResult(False, allowed.reason, "denied")))
            continue
        pre = session.hooks.run_pre(call.name)
        if _hook_configured(session, "pre_tool", call.name):
            _trace(session, "hooks", f"pre {call.name}: {'blocked' if pre.blocked else 'ok'}", stage="hooks", output=pre.output)
        if pre.blocked:
            session.context.add(_tool_message(call, ToolResult(False, pre.output, "hook_blocked")))
            continue
        if session.appa is not None and session.appa_child:
            decision = session.appa.check_call(call.name, arguments, call.id, session.appa_child)
            _trace(session, "appa", f"{decision.decision} {call.name}", stage="tools", tool=call.name)
            if decision.decision not in ("allow_call", "ack"):
                session.context.add(_tool_message(call, ToolResult(False, decision.message(), "appa_blocked")))
                continue
        session.current_call = call
        try:
            result = session.registry.call(call.name, call.arguments, ctx)
        finally:
            session.current_call = None
        post = session.hooks.run_post(call.name)
        if _hook_configured(session, "post_tool", call.name):
            _trace(session, "hooks", f"post {call.name}", stage="hooks", output=post.output)
        text = format_tool_result(result)
        if session.appa is not None and session.appa_child:
            reported = session.appa.report_result(call.name, arguments, call.id, text, result.ok, session.appa_child)
            if reported.decision == "replace_output" and reported.output is not None:
                text = reported.output
            elif reported.decision == "deliver_value" and reported.value is not None:
                text = reported.value
            elif reported.decision not in ("ack", "allow_call"):
                text = reported.message()
        if post.output:
            text = f"{text}\n{post.output}"
        _trace(
            session,
            "tool",
            f"{call.name} -> {result.error_code or 'ok'}",
            stage="tools",
            tool=call.name,
            ok=result.ok,
            error_code=result.error_code,
            output=text,
        )
        session.context.add(Message("tool", text, tool_call_id=call.id, name=call.name))


def _spawn(session: Session, task: str) -> str:
    child_turns = _turn_cap(session.settings, depth=1)
    opened = None
    child_task = task
    if session.appa is not None:
        call_id = session.current_call.id if session.current_call is not None else "spawn"
        opened = session.appa.open_child(task, call_id)
        if opened.context:
            child_task = f"{task}\n\n{opened.context}"
    result = run(
        child_task,
        workspace=session.workspace,
        settings=session.settings,
        providers=session.providers,
        decisions=session.decisions,
        router=session.router,
        registry=session.registry,
        on_text=session.on_text,
        echo=session.echo,
        depth=session.depth + 1,
        scope=f"{session.scope}:sub:{task[:40]}",
        trace=session.trace,
        appa=session.appa,
        appa_child=opened.child_id if opened is not None else None,
    )
    if result.text.strip():
        summary = result.text.strip()
    elif result.reason == "turn_limit":
        summary = f"Sub-agent hit its turn limit of {child_turns} before it produced a summary."
    else:
        summary = "Sub-agent stopped before it produced a summary."
    if session.appa is None or opened is None:
        return summary
    call_id = session.current_call.id if session.current_call is not None else "spawn"
    return session.appa.finish_child(opened.child_id, summary, task, call_id)


def _authorize(session: Session, call: ToolCall) -> Permit:
    permissions = session.settings.permissions
    name = call.name
    if name in permissions.deny_tools:
        return Permit(False, "denied by configuration")
    if name in ("read_file", "grep", "glob"):
        return Permit(True, "")
    if name in ("bash", "write_file", "edit_file"):
        subject = _subject(name, call.arguments)
        if any(pattern and pattern in subject for pattern in permissions.deny_patterns):
            return Permit(False, "denied by configuration")
        if name in permissions.allow_tools or any(pattern and pattern in subject for pattern in permissions.allow_patterns):
            return Permit(True, "")
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        return session.decisions.permit(name, arguments, session.task)
    return Permit(True, "")


def _subject(tool_name: str, arguments) -> str:
    if not isinstance(arguments, dict):
        return ""
    if tool_name == "bash":
        return str(arguments.get("command") or "")
    return str(arguments.get("path") or "")


def _finished(session: Session, reply: str) -> bool:
    done = session.decisions.task_done(session.task, reply)
    return done is None or done


def _tool_message(call: ToolCall, result: ToolResult) -> Message:
    return Message("tool", format_tool_result(result), tool_call_id=call.id, name=call.name)


def _system_prompt(workspace: Path) -> str:
    parts = [SYSTEM_PROMPT.strip()]
    agents = workspace / "AGENTS.md"
    if agents.is_file():
        parts.append("Project context:\n" + agents.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def _turn_cap(settings: Settings, depth: int) -> int:
    if depth == 0:
        return settings.max_turns
    return max(1, min(settings.subagent_max_turns, settings.max_turns // 2 or 1))


def _last_assistant_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "assistant" and not message.tool_calls and message.content.strip():
            return message.content.strip()
    return ""


def _stream_text(session: Session, chunk: str) -> None:
    session.on_text(chunk)
    _trace(session, "text", chunk, stage="model", log=False)


def _hook_configured(session: Session, phase: str, tool_name: str) -> bool:
    specs = getattr(session.settings, phase if phase != "stop" else "stop_hooks")
    return any(spec.tool in (None, tool_name) for spec in specs)


def _trace(session: Session, kind: str, message: str, **fields) -> None:
    session.trace.event(kind, message, **fields)


def _echo(session: Session, text: str) -> None:
    if session.echo and not session.trace.dev:
        print(text, file=sys.stderr, flush=True)
