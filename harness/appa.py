"""OpenAPPA checks for a sub-agent: the spawn, its tools, and the summary.

The harness speaks the runtime wire protocol (protocol 1, the claude-code
adapter) at POST /hook. spawn_agent is the Agent tool on that adapter, which
is how a coding-agent host names a sub-agent. A missing or failed runtime
refuses the spawn. The child does not start, and its summary does not reach
the parent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from harness.errors import AppaError

ADAPTER = "claude-code"
PROTOCOL = 1
CONTROL_TOOL = "mcp__appa__execute_remedy_plan"

# Host tool names the claude-code adapter identifies. Other names are sent as
# written and become host/claude-code/<name>, which a policy must declare.
TOOL_NAMES = {
    "read_file": "Read",
    "edit_file": "Edit",
    "write_file": "Write",
    "bash": "Bash",
    "grep": "Grep",
    "glob": "Glob",
    "spawn_agent": "Agent",
}


@dataclass
class Decision:
    decision: str
    spawn_binding: str | None = None
    feedback: str | None = None
    offers: list | None = None
    reason: str | None = None
    output: str | None = None
    value: str | None = None
    text: str | None = None
    detail: str | None = None

    def message(self) -> str:
        return self.feedback or self.reason or self.detail or self.decision


@dataclass
class OpenedChild:
    child_id: str
    binding: str
    context: str | None


class AppaClient:
    def __init__(self, base_url: str, timeout: float = 30):
        root = base_url.rstrip("/")
        if root.endswith("/hook"):
            root = root[: -len("/hook")]
        self.base_url = root
        self.timeout = timeout

    def post(self, event: dict) -> Decision:
        body = json.dumps(event, allow_nan=False).encode()
        request = Request(
            f"{self.base_url}/hook",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise AppaError(f"OpenAPPA did not answer: {exc}") from exc
        if not isinstance(payload, dict) or "decision" not in payload:
            raise AppaError("OpenAPPA returned a response without a decision")
        return Decision(
            decision=str(payload.get("decision")),
            spawn_binding=payload.get("spawn_binding"),
            feedback=payload.get("feedback"),
            offers=payload.get("offers") if isinstance(payload.get("offers"), list) else None,
            reason=payload.get("reason"),
            output=payload.get("output"),
            value=payload.get("value"),
            text=payload.get("text"),
            detail=payload.get("detail"),
        )

    def execute_remedy(self, offer_id: str, actor: str) -> None:
        """Carry a pass_control remedy to the runtime's MCP endpoint."""
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "execute_remedy_plan",
                    "arguments": {"offer_id": offer_id, "label": {}, "_appa_actor": actor},
                },
            }
        ).encode()
        request = Request(
            f"{self.base_url}/mcp",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise AppaError(f"OpenAPPA did not carry the remedy: {exc}") from exc


class AppaSession:
    def __init__(self, client: AppaClient, root_id: str | None = None):
        self.client = client
        self.root_id = root_id or uuid4().hex
        self._children = 0

    def start(self, task: str) -> None:
        started = self._send(event="session_start", inventory=_inventory())
        if started.decision not in ("ack", "context"):
            raise AppaError(started.message())
        prompted = self._send(event="prompt", text=task[:4000])
        if prompted.decision not in ("ack", "context"):
            raise AppaError(prompted.message())

    def check_call(self, tool: str, arguments: dict, call_id: str, child_id: str | None = None) -> Decision:
        return self._send(
            event="tool_call",
            child_id=child_id,
            tool=_wire_tool(tool),
            arguments=arguments,
            call_id=call_id,
        )

    def report_result(self, tool: str, arguments: dict, call_id: str, text: str, ok: bool, child_id: str) -> Decision:
        outcome = {"status": "success", "body": text} if ok else {"status": "failure", "message": text}
        return self._send(
            event="tool_result",
            child_id=child_id,
            tool=_wire_tool(tool),
            arguments=arguments,
            call_id=call_id,
            outcome=outcome,
        )

    def open_child(self, task: str, call_id: str) -> OpenedChild:
        arguments = {"task": task}
        decision = self.check_call("spawn_agent", arguments, call_id)
        if decision.decision == "deny_call" and self._declare_return(decision):
            decision = self.check_call("spawn_agent", arguments, call_id)
        if decision.decision != "allow_call" or not decision.spawn_binding:
            raise AppaError(decision.message())
        self._children += 1
        child_id = f"sub-{self._children}"
        started = self._send(event="child_start", child_id=child_id, spawn_binding=decision.spawn_binding)
        if started.decision == "refuse":
            raise AppaError(started.message())
        if started.decision not in ("ack", "context"):
            raise AppaError(started.message())
        return OpenedChild(child_id, decision.spawn_binding, started.text if started.decision == "context" else None)

    def finish_child(self, child_id: str, summary: str, task: str, call_id: str) -> str:
        ended = self._send(event="child_end", child_id=child_id, value=summary)
        if ended.decision == "block":
            self._report_spawn(task, call_id, child_id, None, blocked=True)
            raise AppaError(ended.message())
        if ended.decision == "child_return":
            delivered = ended.value if ended.value is not None else ""
        elif ended.decision == "ack":
            delivered = summary
        else:
            raise AppaError(ended.message())
        reported = self._report_spawn(task, call_id, child_id, delivered, blocked=False)
        if reported.decision == "block":
            raise AppaError(reported.message())
        if reported.decision == "deliver_value" and reported.value is not None:
            return reported.value
        if reported.decision == "replace_output" and reported.output is not None:
            return reported.output
        if reported.decision not in ("ack", "deliver_value", "replace_output"):
            raise AppaError(reported.message())
        return delivered

    def _declare_return(self, decision: Decision) -> bool:
        offer_id = _spoken_offer(decision.offers or [])
        if offer_id is None:
            return False
        control = self.check_call(CONTROL_TOOL, {"offer_id": offer_id, "label": {}}, f"remedy-{offer_id}")
        if control.decision == "pass_control":
            self.client.execute_remedy(offer_id, f"cc:{self.root_id}")
        return True

    def _report_spawn(self, task: str, call_id: str, child_id: str, value: str | None, blocked: bool) -> Decision:
        if blocked:
            outcome = {"status": "failure", "message": "OpenAPPA withheld the sub-agent return"}
        else:
            outcome = {"status": "success", "body": value or ""}
        return self._send(
            event="spawn_result",
            tool="Agent",
            arguments={"task": task},
            call_id=call_id,
            spawned_id=child_id,
            value=value,
            outcome=outcome,
        )

    def _send(self, event: str, **fields) -> Decision:
        payload = {"protocol": PROTOCOL, "adapter": ADAPTER, "event": event, "root_id": self.root_id}
        for key, value in fields.items():
            if value is not None:
                payload[key] = value
        return self.client.post(payload)


def _inventory() -> dict:
    names = ("Agent", "Read", "Edit", "Write", "Bash", "Grep", "Glob")
    return {
        "tools": [{"name": name, "tool": name} for name in names],
        "sources": [{"server": "builtin", "status": "complete", "dynamic": False}],
    }


def _wire_tool(name: str) -> str:
    if name == CONTROL_TOOL:
        return name
    return TOOL_NAMES.get(name, name)


def _spoken_offer(offers: list) -> str | None:
    for offer in offers:
        if not isinstance(offer, dict) or not offer.get("offer_id"):
            continue
        returns = offer.get("returns")
        if returns in (None, "as_spoken"):
            return str(offer["offer_id"])
    return None
