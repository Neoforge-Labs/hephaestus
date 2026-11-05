"""Fail-fast settings (spec: settings). Experimental.

``HephSettings`` loads ``HEPH_*`` environment variables. In ``prod`` it refuses
to construct unless every name in ``required_in_prod`` holds a non-blank value,
and it reports *all* missing names at once. Secrets are ``SecretStr`` and input
values are hidden from validation errors, so the object is safe to log.

Needs the ``settings`` extra: ``pip install "hephkit[settings]"``.
"""

import os
from collections.abc import Callable
from typing import Any, ClassVar, Literal, Self

from pydantic import SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["HephSettings", "SettingsError"]


class SettingsError(RuntimeError):
    """Required settings are missing. ``missing`` lists field names (never
    values) in declaration order. ``unused_env`` lists prefixed environment
    variables that match no setting (likely typos); it is informational."""

    def __init__(self, missing: list[str], unused_env: list[str] | None = None) -> None:
        self.missing = missing
        self.unused_env = unused_env or []
        message = "missing required settings: " + ", ".join(missing)
        for name in self.unused_env:
            message += f"; note that {name} is set and matches no setting"
        super().__init__(message)


def _is_blank(value: object) -> bool:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return value is None or (isinstance(value, str) and not value.strip())


class HephSettings(BaseSettings):
    """Base settings. Subclasses add fields and may set ``required_in_prod`` to
    extra names; those are merged after the inherited ones.

    Environment names are matched case-insensitively. Setting two casings of
    the same name (``HEPH_SERVICE_NAME`` and ``heph_service_name``) is
    unsupported: there is no defined precedence.

    Construction raises ``SettingsError`` when required settings are missing:
    fields with no default, plus (in ``prod``) every ``required_in_prod`` name.
    All are reported in one go. Any other invalid value raises pydantic's
    ``ValidationError`` unchanged.
    """

    model_config = SettingsConfigDict(env_prefix="HEPH_", hide_input_in_errors=True)

    required_in_prod: ClassVar[tuple[str, ...]] = ("database_url",)

    env: Literal["dev", "test", "prod"] = "dev"
    service_name: str
    otlp_endpoint: str = "http://localhost:54318"
    database_url: SecretStr | None = None
    log_level: str = "INFO"

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        inherited: tuple[str, ...] = ()
        for base in cls.__mro__[1:][::-1]:
            inherited = (*inherited, *(n for n in vars(base).get("required_in_prod", ()) if n not in inherited))
        own = vars(cls).get("required_in_prod", ())
        cls.required_in_prod = (*inherited, *(n for n in own if n not in inherited))

    @classmethod
    def _unused_env(cls) -> list[str]:
        prefix = str(cls.model_config.get("env_prefix", "")).lower()
        return sorted(
            k for k in os.environ if k.lower().startswith(prefix) and k.lower()[len(prefix) :] not in cls.model_fields
        )

    @model_validator(mode="wrap")
    @classmethod
    def _fail_fast(cls, data: Any, handler: Callable[[Any], Self]) -> Self:
        required = set(cls.required_in_prod)
        try:
            model = handler(data)
        except ValidationError as err:
            errors = err.errors(include_input=False, include_url=False)
            if not errors or not isinstance(data, dict) or any(e["type"] != "missing" for e in errors):
                raise
            absent = {str(e["loc"][0]) for e in errors}
            if data.get("env") == "prod":
                absent |= {n for n in required if _is_blank(data.get(n))}
            raise cls._missing_error(absent) from None
        if model.env == "prod":
            blank = {n for n in required if _is_blank(getattr(model, n, None))}
            if blank:
                raise cls._missing_error(blank)
        return model

    @classmethod
    def _missing_error(cls, names: set[str]) -> SettingsError:
        ordered = [n for n in cls.model_fields if n in names]
        ordered += sorted(names.difference(cls.model_fields))
        return SettingsError(ordered, cls._unused_env())
