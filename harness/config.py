"""Layered harness settings.

Later layers win: built-in defaults, ~/.agent-harness/settings.json,
.agent/settings.json, .agent/settings.local.json, then environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from harness.errors import ConfigError


DEFAULT_CONTEXT_LIMIT = 100_000
DEFAULT_REPLY_RESERVE = 4_000
DEFAULT_SUMMARY_CAP = 8_000
DEFAULT_MAX_TURNS = 30
DEFAULT_SUBAGENT_TURNS = 10
DEFAULT_CONFIDENCE = 0.5
DEFAULT_OPENJEV_URL = "http://127.0.0.1:8791/v1/systemone"
DEFAULT_OPENJEV_MODEL = "open-jev"


@dataclass
class ModelEntry:
    id: str
    provider: str
    model: str
    context_limit: int
    notes: str = ""


@dataclass
class HookSpec:
    command: str
    tool: str | None = None


@dataclass
class Permissions:
    deny_tools: list[str] = field(default_factory=list)
    allow_tools: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)
    allow_patterns: list[str] = field(default_factory=list)


@dataclass
class Settings:
    models: list[ModelEntry] = field(default_factory=list)
    default_model: str = ""
    context_limit: int = DEFAULT_CONTEXT_LIMIT
    max_turns: int = DEFAULT_MAX_TURNS
    subagent_max_turns: int = DEFAULT_SUBAGENT_TURNS
    reply_reserve: int = DEFAULT_REPLY_RESERVE
    summary_token_cap: int = DEFAULT_SUMMARY_CAP
    confidence_min: float = DEFAULT_CONFIDENCE
    permissions: Permissions = field(default_factory=Permissions)
    pre_tool: list[HookSpec] = field(default_factory=list)
    post_tool: list[HookSpec] = field(default_factory=list)
    stop_hooks: list[HookSpec] = field(default_factory=list)
    openjev_base_url: str = DEFAULT_OPENJEV_URL
    openjev_model: str = DEFAULT_OPENJEV_MODEL
    pinned_model: str | None = None

    def model_by_id(self, model_id: str) -> ModelEntry | None:
        for entry in self.models:
            if entry.id == model_id:
                return entry
        return None


def load_settings(
    workspace: Path,
    *,
    user_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> Settings:
    """Load settings for a workspace. Pass env to avoid reading the process environment."""
    environment = os.environ if env is None else env
    home = user_dir if user_dir is not None else Path.home() / ".agent-harness"
    data: dict = {}
    for path in (
        home / "settings.json",
        workspace / ".agent" / "settings.json",
        workspace / ".agent" / "settings.local.json",
    ):
        overlay = _read_json(path)
        if overlay is not None:
            data = _merge(data, overlay)
    return _settings_from(data, environment)


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return loaded


def _merge(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _settings_from(data: dict, env: dict[str, str]) -> Settings:
    models = _models(data.get("models") or [])
    ids = [entry.id for entry in models]
    if len(ids) != len(set(ids)):
        raise ConfigError("model catalog ids must be unique")
    default_model = str(data.get("default_model") or "")
    if default_model and default_model not in ids:
        raise ConfigError(f"default_model {default_model!r} is not in the catalog")
    permissions = _permissions(data.get("permissions") or {})
    hooks = data.get("hooks") or {}
    if not isinstance(hooks, dict):
        raise ConfigError("hooks must be an object")
    settings = Settings(
        models=models,
        default_model=default_model,
        context_limit=_positive(data.get("context_limit", DEFAULT_CONTEXT_LIMIT), "context_limit"),
        max_turns=_positive(data.get("max_turns", DEFAULT_MAX_TURNS), "max_turns"),
        subagent_max_turns=_positive(
            data.get("subagent_max_turns", DEFAULT_SUBAGENT_TURNS), "subagent_max_turns"
        ),
        reply_reserve=_non_negative(data.get("reply_reserve", DEFAULT_REPLY_RESERVE), "reply_reserve"),
        summary_token_cap=_positive(
            data.get("summary_token_cap", DEFAULT_SUMMARY_CAP), "summary_token_cap"
        ),
        confidence_min=_confidence(data.get("confidence_min", DEFAULT_CONFIDENCE)),
        permissions=permissions,
        pre_tool=_hooks(hooks.get("pre_tool")),
        post_tool=_hooks(hooks.get("post_tool")),
        stop_hooks=_hooks(hooks.get("stop")),
        openjev_base_url=str(data.get("openjev_base_url") or DEFAULT_OPENJEV_URL),
        openjev_model=str(data.get("openjev_model") or DEFAULT_OPENJEV_MODEL),
        pinned_model=None,
    )
    if "AGENT_CONTEXT_LIMIT" in env and env["AGENT_CONTEXT_LIMIT"] != "":
        settings.context_limit = _positive(env["AGENT_CONTEXT_LIMIT"], "AGENT_CONTEXT_LIMIT")
    if "AGENT_MAX_TURNS" in env and env["AGENT_MAX_TURNS"] != "":
        settings.max_turns = _positive(env["AGENT_MAX_TURNS"], "AGENT_MAX_TURNS")
    if env.get("OPENJEV_BASE_URL"):
        settings.openjev_base_url = env["OPENJEV_BASE_URL"]
    if env.get("OPENJEV_MODEL"):
        settings.openjev_model = env["OPENJEV_MODEL"]
    if env.get("AGENT_MODEL"):
        pinned = env["AGENT_MODEL"]
        if pinned not in ids:
            raise ConfigError(f"AGENT_MODEL {pinned!r} is not in the catalog")
        settings.pinned_model = pinned
    return settings


def _models(raw) -> list[ModelEntry]:
    if not isinstance(raw, list):
        raise ConfigError("models must be a list")
    entries: list[ModelEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ConfigError("each model must be an object")
        provider = item.get("provider")
        if provider not in ("openai", "anthropic"):
            raise ConfigError("model provider must be 'openai' or 'anthropic'")
        try:
            entries.append(
                ModelEntry(
                    id=str(item["id"]),
                    provider=provider,
                    model=str(item["model"]),
                    context_limit=_positive(item["context_limit"], "context_limit"),
                    notes=str(item.get("notes") or ""),
                )
            )
        except KeyError as exc:
            raise ConfigError(f"model entry is missing {exc.args[0]}") from exc
    return entries


def _permissions(raw) -> Permissions:
    if not isinstance(raw, dict):
        raise ConfigError("permissions must be an object")
    return Permissions(
        deny_tools=_strings(raw.get("deny_tools"), "deny_tools"),
        allow_tools=_strings(raw.get("allow_tools"), "allow_tools"),
        deny_patterns=_strings(raw.get("deny_patterns"), "deny_patterns"),
        allow_patterns=_strings(raw.get("allow_patterns"), "allow_patterns"),
    )


def _hooks(raw) -> list[HookSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("hook lists must be arrays")
    specs: list[HookSpec] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("command"):
            raise ConfigError("each hook needs a command")
        tool = item.get("tool")
        specs.append(HookSpec(command=str(item["command"]), tool=str(tool) if tool else None))
    return specs


def _strings(raw, label: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ConfigError(f"{label} must be a list of strings")
    return list(raw)


def _positive(value, label: str) -> int:
    number = _int(value, label)
    if number < 1:
        raise ConfigError(f"{label} must be a positive integer")
    return number


def _non_negative(value, label: str) -> int:
    number = _int(value, label)
    if number < 0:
        raise ConfigError(f"{label} must be zero or greater")
    return number


def _int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError(f"{label} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{label} must be an integer") from exc


def _confidence(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError("confidence_min must be a number")
    try:
        number = float(value)
    except ValueError as exc:
        raise ConfigError("confidence_min must be a number") from exc
    if not 0 <= number <= 1:
        raise ConfigError("confidence_min must be between 0 and 1")
    return number
