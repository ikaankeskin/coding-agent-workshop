"""Errors the harness raises when it cannot continue."""


class HarnessError(Exception):
    """Base error for expected harness failures."""


class ConfigError(HarnessError):
    """Settings could not be loaded or were inconsistent."""


class OpenJevError(HarnessError):
    """The decision server could not answer."""


class AppaError(HarnessError):
    """OpenAPPA refused a sub-agent or could not be reached."""


class NoModelError(HarnessError):
    """No catalog model can hold the current context."""


class ContextLimitError(HarnessError):
    """Compression could not bring the context under the budget."""
