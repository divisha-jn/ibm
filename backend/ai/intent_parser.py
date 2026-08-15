"""Natural-language what-if parser with strict validation."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .granite import GraniteClient
from .prompts import build_what_if_messages


OperationName = Literal[
    "SET_PRIORITY",
    "SET_REQUIRED_DURATION",
    "DISABLE_STATION",
    "SET_ELIGIBLE_STATIONS",
]


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: OperationName
    request_id: str | None = None
    station_id: str | None = None
    station_ids: list[str] | None = None
    value: int | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "Operation":
        if self.operation == "SET_PRIORITY":
            if not self.request_id or self.value is None:
                raise ValueError(
                    "SET_PRIORITY requires request_id and integer value."
                )
            if self.value < 0:
                raise ValueError("Priority cannot be negative.")

        elif self.operation == "SET_REQUIRED_DURATION":
            if not self.request_id or self.value is None:
                raise ValueError(
                    "SET_REQUIRED_DURATION requires request_id and seconds."
                )
            if self.value <= 0:
                raise ValueError("Required duration must be positive.")

        elif self.operation == "DISABLE_STATION":
            if not self.station_id:
                raise ValueError("DISABLE_STATION requires station_id.")

        elif self.operation == "SET_ELIGIBLE_STATIONS":
            if not self.request_id or not self.station_ids:
                raise ValueError(
                    "SET_ELIGIBLE_STATIONS requires request_id and station_ids."
                )

        return self


class WhatIfInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["MODIFY_SCENARIO", "UNSUPPORTED"]
    operations: list[Operation] = Field(default_factory=list)
    requires_resolve: bool
    error: str | None = None

    @model_validator(mode="after")
    def validate_interpretation(self) -> "WhatIfInterpretation":
        if self.intent == "MODIFY_SCENARIO":
            if not self.operations:
                raise ValueError(
                    "MODIFY_SCENARIO requires at least one operation."
                )
            if not self.requires_resolve:
                raise ValueError(
                    "Scenario modifications must require a solver re-resolve."
                )
            if self.error:
                raise ValueError(
                    "A supported modification cannot contain an error."
                )

        if self.intent == "UNSUPPORTED":
            if self.operations:
                raise ValueError(
                    "UNSUPPORTED interpretation cannot contain operations."
                )
            if self.requires_resolve:
                raise ValueError(
                    "UNSUPPORTED interpretation cannot require a resolve."
                )

        return self


class IntentParserError(RuntimeError):
    """Raised when Granite's output cannot be safely interpreted."""


def _extract_json(text: str) -> dict[str, Any]:
    """Parse JSON even if a model accidentally wraps it in markdown fences."""
    cleaned = text.strip()

    # Preferred: direct JSON.
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    # Tolerate ```json ... ``` despite the prompt asking for raw JSON.
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fenced:
        try:
            value = json.loads(fenced.group(1))
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

    # Last-resort extraction of the outermost JSON object.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(cleaned[start : end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

    raise IntentParserError("Granite did not return valid JSON.")


def _validate_identifiers(
    interpretation: WhatIfInterpretation,
    scenario_context: dict[str, Any],
) -> None:
    """Prevent Granite from inventing identifiers.

    The parser validates against the current scenario before P4 receives the
    operation.
    """
    requests = {
        str(r.get("request_id"))
        for r in scenario_context.get("requests", [])
        if r.get("request_id") is not None
    }
    stations = {
        str(s)
        for s in scenario_context.get("station_ids", [])
        if s is not None
    }

    for operation in interpretation.operations:
        if operation.request_id and operation.request_id not in requests:
            raise IntentParserError(
                f"Unknown request_id from Granite: {operation.request_id}"
            )

        if operation.station_id and operation.station_id not in stations:
            raise IntentParserError(
                f"Unknown station_id from Granite: {operation.station_id}"
            )

        if operation.station_ids:
            unknown = set(operation.station_ids) - stations
            if unknown:
                raise IntentParserError(
                    f"Unknown station_ids from Granite: {sorted(unknown)}"
                )


def parse_what_if(
    user_query: str,
    scenario_context: dict[str, Any],
    *,
    client: GraniteClient | None = None,
) -> WhatIfInterpretation:
    """Parse a user what-if request into a validated, solver-ready intent."""
    if not user_query or not user_query.strip():
        raise ValueError("user_query cannot be empty.")

    if not isinstance(scenario_context, dict):
        raise TypeError("scenario_context must be a dictionary.")

    granite = client or GraniteClient()

    raw = granite.chat(
        build_what_if_messages(user_query.strip(), scenario_context),
        max_completion_tokens=350,
        temperature=0.0,
    )

    try:
        data = _extract_json(raw)
        interpretation = WhatIfInterpretation.model_validate(data)
    except (ValidationError, IntentParserError) as exc:
        raise IntentParserError(
            f"Granite returned an invalid what-if interpretation: {exc}"
        ) from exc

    _validate_identifiers(interpretation, scenario_context)
    return interpretation


if __name__ == "__main__":
    scenario = {
        "requests": [
            {"request_id": "REQ_001"},
            {"request_id": "REQ_002"},
        ],
        "station_ids": ["GS_SG_01", "GS_SG_02"],
    }

    result = parse_what_if(
        "What if REQ_002 becomes priority 10?",
        scenario,
    )
    print(result.model_dump_json(indent=2))