"""Mission Ops Copilot AI layer."""

from .granite import GraniteClient, GraniteConfig
from .explain import explain_conflict
from .intent_parser import parse_what_if

__all__ = ["GraniteClient", "GraniteConfig", "explain_conflict", "parse_what_if"]
