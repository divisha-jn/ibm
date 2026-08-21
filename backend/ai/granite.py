"""watsonx.ai / IBM Granite client.

This module contains all direct communication with Granite so the rest of the
application does not need to know about authentication or watsonx details.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_WATSONX_URL = "https://jp-tok.ml.cloud.ibm.com"
DEFAULT_MODEL_ID = "llama-3-3-70b-instruct"
DEFAULT_API_VERSION = "2025-10-25"


class GraniteConfigurationError(RuntimeError):
    """Raised when the Granite client is missing required configuration."""


class GraniteAPIError(RuntimeError):
    """Raised when watsonx.ai returns an error."""


@dataclass(frozen=True)
class GraniteConfig:
    api_key: str
    project_id: str
    url: str = DEFAULT_WATSONX_URL
    model_id: str = DEFAULT_MODEL_ID
    api_version: str = DEFAULT_API_VERSION
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls) -> "GraniteConfig":
        api_key = os.getenv("WATSONX_APIKEY", "").strip()
        project_id = os.getenv("WATSONX_PROJECT_ID", "").strip()

        if not api_key:
            raise GraniteConfigurationError(
                "WATSONX_APIKEY is not configured. Add it to your .env file."
            )
        if not project_id:
            raise GraniteConfigurationError(
                "WATSONX_PROJECT_ID is not configured. Add it to your .env file."
            )

        return cls(
            api_key=api_key,
            project_id=project_id,
            url=os.getenv("WATSONX_URL", DEFAULT_WATSONX_URL).rstrip("/"),
            model_id=os.getenv("WATSONX_MODEL_ID", DEFAULT_MODEL_ID),
            api_version=os.getenv(
                "WATSONX_API_VERSION", DEFAULT_API_VERSION
            ),
            timeout_seconds=int(os.getenv("WATSONX_TIMEOUT_SECONDS", "60")),
        )


class GraniteClient:
    """Small, dependency-light client for the watsonx.ai chat API."""

    def __init__(self, config: GraniteConfig | None = None) -> None:
        self.config = config or GraniteConfig.from_env()

    def _get_iam_token(self) -> str:
        """Exchange the IBM Cloud API key for an IAM bearer token."""
        response = requests.post(
            "https://iam.cloud.ibm.com/identity/token",
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": self.config.api_key,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.config.timeout_seconds,
        )

        if not response.ok:
            raise GraniteAPIError(
                f"IAM authentication failed ({response.status_code}): "
                f"{response.text[:1000]}"
            )

        try:
            return response.json()["access_token"]
        except (ValueError, KeyError) as exc:
            raise GraniteAPIError(
                "IAM response did not contain an access_token."
            ) from exc

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_completion_tokens: int = 500,
        temperature: float = 0.0,
    ) -> str:
        """Send a chat request to Granite and return the assistant text."""
        token = self._get_iam_token()

        endpoint = (
            f"{self.config.url}/ml/v1/text/chat"
            f"?version={self.config.api_version}"
        )

        payload: dict[str, Any] = {
            "messages": messages,
            "project_id": self.config.project_id,
            "model_id": self.config.model_id,
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
        }

        response = requests.post(
            endpoint,
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=self.config.timeout_seconds,
        )

        if not response.ok:
            raise GraniteAPIError(
                f"watsonx.ai request failed ({response.status_code}): "
                f"{response.text[:2000]}"
            )

        try:
            data = response.json()
            return self._extract_text(data)
        except (ValueError, KeyError, TypeError) as exc:
            raise GraniteAPIError(
                f"Unexpected watsonx.ai response: {response.text[:2000]}"
            ) from exc

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        """Extract assistant text from the current chat response shape."""
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise KeyError("choices")

        message = choices[0].get("message", {})
        content = message.get("content")

        if isinstance(content, str):
            return content.strip()

        # Be tolerant of content-part responses.
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            if text_parts:
                return "".join(text_parts).strip()

        raise KeyError("choices[0].message.content")

    def health_check(self) -> str:
        """Minimal live test: ask Granite for a deterministic response."""
        return self.chat(
            [
                {
                    "role": "user",
                    "content": "Reply with exactly: MISSION_OPS_GRANITE_OK",
                }
            ],
            max_completion_tokens=20,
            temperature=0.0,
        )