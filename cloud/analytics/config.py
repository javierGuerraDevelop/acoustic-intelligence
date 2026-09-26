"""Environment configuration and key-pair loading for the Snowflake adapter.

Secrets are read from the process environment (or an ignored local .env loaded
by the launcher) and never logged or embedded in errors. ``SNOWFLAKE_PRIVATE_KEY_B64``
holds base64 of either the PEM text or its DER bytes; ``SNOWFLAKE_PRIVATE_KEY_PATH``
is an alternative local file path. The deployed service uses the encrypted
runtime variable form.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Mapping

from .errors import AdapterError

DEFAULT_AI_MODEL = "llama3.3-70b"
DEFAULT_LOGIN_TIMEOUT_SECONDS = 10
DEFAULT_NETWORK_TIMEOUT_SECONDS = 15
DEFAULT_QUERY_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    private_key_der: bytes | None
    private_key_passphrase: str | None
    role: str | None
    warehouse: str | None
    database: str | None
    schema: str | None
    ai_model: str
    login_timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS
    network_timeout_seconds: int = DEFAULT_NETWORK_TIMEOUT_SECONDS
    query_timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SnowflakeConfig":
        values = os.environ if env is None else env

        def required(name: str) -> str:
            value = values.get(name, "").strip()
            if not value:
                raise AdapterError("BAD_INPUT", False)
            return value

        def optional(name: str) -> str | None:
            value = values.get(name, "").strip()
            return value or None

        return cls(
            account=required("SNOWFLAKE_ACCOUNT"),
            user=required("SNOWFLAKE_USER"),
            private_key_der=_load_private_key(values),
            private_key_passphrase=optional("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
            role=optional("SNOWFLAKE_ROLE"),
            warehouse=optional("SNOWFLAKE_WAREHOUSE"),
            database=optional("SNOWFLAKE_DATABASE"),
            schema=optional("SNOWFLAKE_SCHEMA"),
            ai_model=optional("SNOWFLAKE_AI_MODEL") or DEFAULT_AI_MODEL,
            login_timeout_seconds=_int_env(values, "SNOWFLAKE_LOGIN_TIMEOUT_SECONDS",
                                           DEFAULT_LOGIN_TIMEOUT_SECONDS),
            network_timeout_seconds=_int_env(values, "SNOWFLAKE_NETWORK_TIMEOUT_SECONDS",
                                             DEFAULT_NETWORK_TIMEOUT_SECONDS),
            query_timeout_seconds=_int_env(values, "SNOWFLAKE_QUERY_TIMEOUT_SECONDS",
                                           DEFAULT_QUERY_TIMEOUT_SECONDS),
        )

    def connect_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "account": self.account,
            "user": self.user,
            "login_timeout": self.login_timeout_seconds,
            "network_timeout": self.network_timeout_seconds,
            "client_session_keep_alive": False,
        }
        if self.private_key_der is not None:
            kwargs["private_key"] = self.private_key_der
        if self.role:
            kwargs["role"] = self.role
        if self.warehouse:
            kwargs["warehouse"] = self.warehouse
        if self.database:
            kwargs["database"] = self.database
        if self.schema:
            kwargs["schema"] = self.schema
        return kwargs

    def sanitized(self) -> dict[str, object]:
        """Connection summary safe to place in logs or test evidence."""
        return {
            "account": self.account,
            "user": self.user,
            "role": self.role,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
            "ai_model": self.ai_model,
            "has_private_key": self.private_key_der is not None,
        }


def _load_private_key(values: Mapping[str, str]) -> bytes | None:
    encoded = values.get("SNOWFLAKE_PRIVATE_KEY_B64", "").strip()
    if encoded:
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise AdapterError("BAD_INPUT", False) from exc
        return _normalize_key(decoded, values.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"))

    path = values.get("SNOWFLAKE_PRIVATE_KEY_PATH", "").strip()
    if path:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            raise AdapterError("BAD_INPUT", False) from exc
        return _normalize_key(raw, values.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"))
    return None


def _normalize_key(raw: bytes, passphrase: str | None) -> bytes:
    if b"-----BEGIN" not in raw:
        return raw
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:  # pragma: no cover - environment issue
        raise AdapterError("UNAVAILABLE", True) from exc
    password = passphrase.encode("utf-8") if passphrase else None
    try:
        key = serialization.load_pem_private_key(raw, password=password)
        return key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    except (ValueError, TypeError) as exc:
        raise AdapterError("BAD_INPUT", False) from exc


def _int_env(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise AdapterError("BAD_INPUT", False) from exc
    if parsed <= 0:
        raise AdapterError("BAD_INPUT", False)
    return parsed
