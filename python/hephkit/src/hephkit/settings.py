"""Fail-fast settings (spec: settings). Experimental.

``HephSettings`` loads ``HEPH_*`` environment variables. In ``prod`` it refuses
to construct unless every name in ``required_in_prod`` holds a non-blank value,
and it reports *all* missing names at once. Secrets are ``SecretStr`` and input
values are hidden from validation errors, so the object is safe to log.

Needs the ``settings`` extra: ``pip install "hephkit[settings]"``.
"""

from typing import Any, ClassVar, Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["HephSettings", "SettingsError"]


class SettingsError(RuntimeError):
    """Required production settings are missing. ``missing`` lists field names
    (never values) in declaration order."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__("missing required settings in prod: " + ", ".join(missing))
        self.missing = missing


def _is_blank(value: object) -> bool:
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return value is None or (isinstance(value, str) and not value.strip())


class HephSettings(BaseSettings):
    """Base settings. Subclasses add fields and may set ``required_in_prod`` to
    extra names; those are merged after the inherited ones."""

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

    @model_validator(mode="after")
    def _require_secrets_in_prod(self) -> Self:
        if self.env != "prod":
            return self
        required = set(self.required_in_prod)
        missing = [n for n in type(self).model_fields if n in required and _is_blank(getattr(self, n, None))]
        # Names declared in required_in_prod but not fields are always missing.
        missing += [n for n in self.required_in_prod if n not in type(self).model_fields]
        if missing:
            raise SettingsError(missing)
        return self
