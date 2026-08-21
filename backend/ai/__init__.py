"""Mission Ops Copilot AI layer."""

__all__ = ["GraniteClient", "GraniteConfig", "explain_conflict", "parse_what_if"]


def __getattr__(name):
    """Load optional watsonx/Pydantic dependencies only when requested."""
    if name in {"GraniteClient", "GraniteConfig"}:
        from .granite import GraniteClient, GraniteConfig

        return {"GraniteClient": GraniteClient, "GraniteConfig": GraniteConfig}[name]
    if name == "explain_conflict":
        from .explain import explain_conflict

        return explain_conflict
    if name == "parse_what_if":
        from .intent_parser import parse_what_if

        return parse_what_if
    raise AttributeError(name)
