"""Structured error types for basecli.

Every user-facing failure raises a :class:`BaseCliError` (or subclass). The CLI
catches it and emits ``{"error": {...}}`` to stderr with a non-zero exit code.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class BaseCliError(Exception):
    """Base class for all basecli errors.

    ``kind`` is a stable machine-readable string; ``detail`` carries optional
    structured context for the JSON error envelope.
    """

    kind = "error"

    def __init__(self, message: str, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind, "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


class ParseError(BaseCliError):
    """Lexing/parsing failure in an expression."""

    kind = "parse_error"


class EvalError(BaseCliError):
    """Runtime failure while evaluating an expression.

    This is the class used to reproduce Obsidian's
    ``Cannot find function "round" on type Duration`` style messages.
    """

    kind = "eval_error"


class SchemaError(BaseCliError):
    """Malformed ``.base`` file or unresolvable view/formula references."""

    kind = "schema_error"


class VaultError(BaseCliError):
    """Vault could not be located or scanned."""

    kind = "vault_error"


class UsageError(BaseCliError):
    """Bad CLI invocation (unknown view, missing file, etc.)."""

    kind = "usage_error"
