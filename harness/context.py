"""Everything the model can see on a turn, including compression."""

from __future__ import annotations

from harness.messages import Message, estimate_messages, estimate_text

COMPRESSED_PREFIX = "Session compressed at the context limit. Continue from this state.\n\n"

SUMMARY_SECTIONS = (
    "Task: the user's task, as close to the original wording as possible",
    "Decisions: decisions already made, each with the reason",
    "Files changed: path and one line describing the change, not the file body",
    "Files read: path and the conclusion drawn from that read",
    "Commands: commands whose results still matter, including failing test names and the error lines",
    "Unresolved: unresolved problems, quoted rather than paraphrased when they are errors",
    "Next: what the agent was about to do next",
)


def summary_instructions() -> str:
    lines = "\n".join(f"- {section}" for section in SUMMARY_SECTIONS)
    return (
        "Summarize this coding session for the agent that will continue the work.\n"
        "Keep these sections even if you cut everything else:\n"
        f"{lines}\n"
        "Do not include file bodies or raw tool dumps."
    )


def rewrite_instructions() -> str:
    names = ", ".join(section.split(":", 1)[0] for section in SUMMARY_SECTIONS)
    return (
        "Rewrite the summary below in fewer words. "
        f"Keep the same sections: {names}."
    )


class Context:
    def __init__(self, system: str):
        self.system = system
        self.transcript: list[Message] = []
        self._usage_input: int | None = None
        self._usage_count = 0

    def messages(self) -> list[Message]:
        return [Message("system", self.system), *self.transcript]

    def add(self, message: Message) -> None:
        self.transcript.append(message)

    def note_usage(self, input_tokens: int | None, sent_transcript: int) -> None:
        if input_tokens is None:
            return
        self._usage_input = input_tokens
        self._usage_count = sent_transcript

    def estimate(self) -> int:
        if self._usage_input is None:
            return estimate_messages(self.messages())
        extra = self.transcript[self._usage_count :]
        return self._usage_input + estimate_messages(extra)

    def replace_transcript(self, summary: str) -> None:
        self.transcript = [Message("user", COMPRESSED_PREFIX + summary.strip())]
        self._usage_input = None
        self._usage_count = 0


def over_budget(estimate: int, *, context_limit: int, model_limit: int | None, reply_reserve: int) -> bool:
    ceiling = context_limit if model_limit is None else min(context_limit, model_limit)
    return estimate + reply_reserve >= ceiling


def summary_too_long(summary: str, cap: int) -> bool:
    return estimate_text(summary) > cap
