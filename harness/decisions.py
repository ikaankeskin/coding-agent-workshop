"""OpenJev client and the four decision call sites."""

from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from harness.config import ModelEntry
from harness.errors import OpenJevError


@dataclass
class Permit:
    allowed: bool
    reason: str


class OpenJevClient:
    """POST /v1/systemone. The endpoint is the only request target."""

    def __init__(self, base_url: str, model: str = "open-jev", api_key: str | None = None, timeout: float = 60):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key or None
        self.timeout = timeout

    def ask(self, state, questions: dict) -> dict:
        body = json.dumps(
            {"model": self.model, "state": state, "questions": questions},
            allow_nan=False,
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.base_url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise OpenJevError(str(exc)) from exc
        answers = result.get("answers") if isinstance(result, dict) else None
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise OpenJevError("response question IDs do not match the request")
        return result


class Decisions:
    def __init__(self, client, confidence_min: float = 0.5):
        self.client = client
        self.confidence_min = confidence_min

    def choose_model(self, kind: str, task: str, tokens: int, candidates: list[ModelEntry]) -> str | None:
        criteria = {entry.id: entry.notes or entry.model for entry in candidates}
        questions = {
            "model": {
                "type": "choice",
                "instructions": "Which catalog model should run this work?",
                "criteria": criteria,
            }
        }
        state = f"kind: {kind}\ntokens: {tokens}\ntask: {task[:2000]}"
        answer = self._choice(state, questions, "model")
        if answer is None or answer["choice"] not in criteria:
            return None
        return answer["choice"]

    def permit(self, tool_name: str, arguments: dict, task: str) -> Permit:
        questions = {
            "permit": {
                "type": "choice",
                "instructions": "Should this tool call be allowed?",
                "criteria": {
                    "allow": "The call is safe and relevant to the user's task",
                    "deny": "The call is destructive, out of scope, or unrelated",
                },
            }
        }
        state = (
            f"task: {task[:2000]}\n"
            f"tool: {tool_name}\n"
            f"arguments: {json.dumps(arguments, ensure_ascii=False)[:2000]}"
        )
        try:
            answer = self._choice(state, questions, "permit")
        except OpenJevError:
            return Permit(False, "denied because the decision server failed")
        if answer is None or answer["choice"] != "allow":
            reason = "denied because the decision was uncertain" if answer is None else "denied by decision"
            if answer is not None and answer["choice"] == "deny":
                reason = "denied by decision"
            return Permit(False, reason)
        return Permit(True, "")

    def task_done(self, task: str, reply: str) -> bool | None:
        """True when the task is finished, False when it is not, None when the server is down."""
        questions = {
            "done": {
                "type": "noul",
                "instructions": (
                    "Is the user's request fully handled by the work so far and this final reply?"
                ),
            }
        }
        state = f"task: {task[:2000]}\nreply: {reply[:2000]}"
        try:
            result = self._ask(state, questions)
        except OpenJevError:
            return None
        noul = result["answers"]["done"].get("noul")
        if not isinstance(noul, (int, float)) or isinstance(noul, bool):
            return None
        return float(noul) >= 0.5

    def should_spawn(self, task: str, parent_task: str = "") -> bool:
        allowed, _reason = self.spawn_gate(task, parent_task)
        return allowed

    def spawn_gate(self, task: str, parent_task: str = "") -> tuple[bool, str]:
        questions = {
            "route": {
                "type": "choice",
                "instructions": "Should this investigation run in an isolated sub-agent?",
                "criteria": {
                    "spawn": "The investigation is large enough to isolate in its own context",
                    "inline": "The work should stay in the main conversation",
                },
            }
        }
        state = f"investigation: {task[:2000]}"
        if parent_task.strip():
            state = f"user request: {parent_task.strip()[:2000]}\n{state}"
        try:
            answer = self._choice(state, questions, "route")
        except OpenJevError:
            return False, "OpenJev could not be reached. Do this investigation in the main conversation."
        if answer is None:
            return False, "OpenJev was not confident enough to start a sub-agent. Do this investigation in the main conversation."
        if answer["choice"] != "spawn":
            return False, "OpenJev chose to keep this investigation in the main conversation."
        return True, ""

    def _choice(self, state, questions: dict, question_id: str) -> dict | None:
        result = self._ask(state, questions)
        answer = result["answers"][question_id]
        choice = answer.get("choice")
        confidence = answer.get("confidence")
        if not isinstance(choice, str):
            return None
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return None
        if float(confidence) < self.confidence_min:
            return None
        return {"choice": choice, "confidence": float(confidence)}

    def _ask(self, state, questions: dict) -> dict:
        try:
            result = self.client.ask(state, questions)
        except OpenJevError:
            raise
        except Exception as exc:
            raise OpenJevError(str(exc)) from exc
        answers = result.get("answers") if isinstance(result, dict) else None
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise OpenJevError("response question IDs do not match the request")
        return result
