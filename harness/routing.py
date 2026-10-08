"""Choose a catalog model and keep that choice for the conversation."""

from __future__ import annotations

import os
from collections.abc import Callable

from harness.config import ModelEntry, Settings
from harness.decisions import Decisions
from harness.errors import NoModelError, OpenJevError


def default_has_key(provider: str) -> bool:
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return False


class Router:
    def __init__(self, settings: Settings, decisions: Decisions, has_key: Callable[[str], bool] | None = None, trace=None):
        self.settings = settings
        self.decisions = decisions
        self.has_key = has_key or default_has_key
        self.trace = trace
        self._sticky: dict[str, str] = {}

    def sticky(self, scope: str) -> ModelEntry | None:
        model_id = self._sticky.get(scope)
        if not model_id:
            return None
        return self.settings.model_by_id(model_id)

    def fits(self, entry: ModelEntry, token_estimate: int) -> bool:
        if not self.has_key(entry.provider):
            return False
        return entry.context_limit > token_estimate + self.settings.reply_reserve

    def eligible(self, token_estimate: int) -> list[ModelEntry]:
        return [entry for entry in self.settings.models if self.fits(entry, token_estimate)]

    def choose(
        self,
        *,
        kind: str,
        scope: str,
        task: str,
        token_estimate: int,
        refit: bool = False,
        remember: bool = True,
    ) -> ModelEntry:
        eligible = self.eligible(token_estimate)
        if not eligible:
            raise NoModelError("No catalog model can fit this context.")

        if kind == "main" and self.settings.pinned_model and not refit:
            pinned = self.settings.model_by_id(self.settings.pinned_model)
            if pinned and self.fits(pinned, token_estimate):
                self._remember(scope, pinned, remember)
                self._emit(kind, pinned, "pinned by AGENT_MODEL", token_estimate)
                return pinned

        if not refit and scope in self._sticky:
            current = self.settings.model_by_id(self._sticky[scope])
            if current and self.fits(current, token_estimate):
                self._emit(kind, current, "kept from earlier in this conversation", token_estimate)
                return current

        if len(eligible) == 1:
            chosen = eligible[0]
            how = "only model that fits this context"
        else:
            chosen, how = self._ask(kind, task, token_estimate, eligible)
        self._remember(scope, chosen, remember)
        self._emit(kind, chosen, how, token_estimate)
        return chosen

    def _ask(self, kind: str, task: str, token_estimate: int, eligible: list[ModelEntry]) -> tuple[ModelEntry, str]:
        picked = None
        try:
            picked = self.decisions.choose_model(kind, task, token_estimate, eligible)
        except OpenJevError:
            picked = None
        if picked:
            found = self.settings.model_by_id(picked)
            if found and found in eligible:
                return found, "chosen by OpenJev"
        return self._fallback(eligible), "OpenJev unavailable or unsure, using fallback"

    def _emit(self, kind: str, entry: ModelEntry, how: str, token_estimate: int) -> None:
        if self.trace is None:
            return
        self.trace.event(
            "route",
            f"{kind} -> {entry.id} ({entry.provider}/{entry.model}): {how}",
            stage="route",
            catalog_id=entry.id,
            provider=entry.provider,
            model=entry.model,
            how=how,
            tokens=token_estimate,
        )

    def _fallback(self, eligible: list[ModelEntry]) -> ModelEntry:
        default = self.settings.model_by_id(self.settings.default_model) if self.settings.default_model else None
        if default and default in eligible:
            return default
        return max(eligible, key=lambda entry: entry.context_limit)

    def _remember(self, scope: str, entry: ModelEntry, remember: bool) -> None:
        if remember:
            self._sticky[scope] = entry.id
