"""hephkit.settings: fail-fast, never-leak settings (experimental)."""

import copy
import pprint
from typing import ClassVar

import pytest
from pydantic import SecretStr, ValidationError

from hephkit.settings import HephSettings, SettingsError

SECRET = "postgres://app:s3cr3t-pw@db/prod"
STRIPE = "sk_live_topsecret"


class PaySettings(HephSettings):
    required_in_prod: ClassVar[tuple[str, ...]] = ("stripe_key",)
    stripe_key: SecretStr | None = None


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.upper().startswith("HEPH_"):
            monkeypatch.delenv(key)


def test_service_name_alone_loads_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEPH_SERVICE_NAME", "x")
    s = HephSettings()
    assert s.env == "dev"
    assert s.service_name == "x"
    assert s.otlp_endpoint == "http://localhost:54318"
    assert s.database_url is None
    assert s.log_level == "INFO"


def test_prod_reports_all_missing_at_once_in_declaration_order() -> None:
    with pytest.raises(SettingsError) as exc:
        PaySettings(env="prod", service_name="x")
    assert exc.value.missing == ["database_url", "stripe_key"]
    assert "database_url" in str(exc.value) and "stripe_key" in str(exc.value)


def test_required_in_prod_composes_with_base() -> None:
    assert PaySettings.required_in_prod == ("database_url", "stripe_key")
    assert HephSettings.required_in_prod == ("database_url",)


def test_subclass_extending_via_concatenation_does_not_duplicate() -> None:
    class S(HephSettings):
        required_in_prod: ClassVar[tuple[str, ...]] = (*HephSettings.required_in_prod, "stripe_key")
        stripe_key: SecretStr | None = None

    assert S.required_in_prod == ("database_url", "stripe_key")


def test_subclass_without_override_inherits() -> None:
    class S(HephSettings):
        pass

    assert S.required_in_prod == ("database_url",)


def test_partial_missing_reports_only_the_missing() -> None:
    with pytest.raises(SettingsError) as exc:
        PaySettings(env="prod", service_name="x", database_url=SecretStr(SECRET))
    assert exc.value.missing == ["stripe_key"]


def test_prod_with_everything_set_loads() -> None:
    s = PaySettings(env="prod", service_name="x", database_url=SecretStr(SECRET), stripe_key=SecretStr(STRIPE))
    assert s.database_url is not None and s.database_url.get_secret_value() == SECRET


@pytest.mark.parametrize("env", ["dev", "test"])
def test_non_prod_does_not_require_secrets(env: str) -> None:
    s = PaySettings(env=env, service_name="x")  # type: ignore[arg-type]
    assert s.database_url is None and s.stripe_key is None


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t\n"])
def test_blank_secret_counts_as_missing_in_prod(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("HEPH_ENV", "prod")
    monkeypatch.setenv("HEPH_SERVICE_NAME", "x")
    monkeypatch.setenv("HEPH_DATABASE_URL", blank)
    with pytest.raises(SettingsError) as exc:
        HephSettings()
    assert exc.value.missing == ["database_url"]


def test_env_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEPH_ENV", "prod")
    monkeypatch.setenv("HEPH_SERVICE_NAME", "svc")
    monkeypatch.setenv("HEPH_DATABASE_URL", SECRET)
    s = HephSettings()
    assert s.env == "prod" and s.service_name == "svc"


def test_env_var_names_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("heph_service_name", "lower")
    assert HephSettings().service_name == "lower"


def test_unprefixed_env_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICE_NAME", "nope")
    with pytest.raises(ValidationError):
        HephSettings()


@pytest.mark.parametrize("bad", ["staging", "production", "PROD", ""])
def test_unknown_env_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        HephSettings(env=bad, service_name="x")  # type: ignore[arg-type]


def test_service_name_is_required() -> None:
    with pytest.raises(ValidationError):
        HephSettings()


def _prod() -> PaySettings:
    return PaySettings(env="prod", service_name="x", database_url=SecretStr(SECRET), stripe_key=SecretStr(STRIPE))


def test_repr_and_json_never_contain_secret() -> None:
    s = _prod()
    assert SECRET not in repr(s)
    assert SECRET not in s.model_dump_json()
    assert STRIPE not in repr(s) and STRIPE not in s.model_dump_json()


def test_every_rendering_path_hides_the_secret() -> None:
    s = _prod()
    renderings = [
        str(s),
        format(s),
        f"{s}",
        f"{s!r}",
        repr(s.model_dump()),
        str(s.model_dump()),
        pprint.pformat(s),
        pprint.pformat(s.model_dump()),
        repr(copy.deepcopy(s)),
        repr(copy.copy(s)),
        repr(s.model_copy(update={"log_level": "DEBUG"})),
        repr(s.model_fields_set),
        s.model_dump_json(indent=2),
    ]
    for text in renderings:
        assert SECRET not in text and STRIPE not in text


def test_validation_error_for_another_field_does_not_reveal_secret() -> None:
    with pytest.raises(ValidationError) as exc:
        HephSettings(env="staging", service_name="x", database_url=SecretStr(SECRET))  # type: ignore[arg-type]
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value.errors())


def test_mistyped_env_var_value_is_not_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo like HEPH_DATABASE_URI must fail without printing its value."""
    monkeypatch.setenv("HEPH_SERVICE_NAME", "x")
    monkeypatch.setenv("HEPH_DATABASE_URI", SECRET)
    try:
        HephSettings()
    except ValidationError as e:
        assert SECRET not in str(e)
        assert SECRET not in repr(e.errors())


def test_wrongly_typed_secret_input_is_not_echoed() -> None:
    with pytest.raises(ValidationError) as exc:
        HephSettings(service_name="x", database_url=12345)  # type: ignore[arg-type]
    assert "12345" not in str(exc.value)


def test_settings_error_message_never_contains_values() -> None:
    with pytest.raises(SettingsError) as exc:
        PaySettings(env="prod", service_name="x", stripe_key=SecretStr("  "))
    assert str(exc.value) == "missing required settings in prod: database_url, stripe_key"
    assert exc.value.missing == ["database_url", "stripe_key"]


def test_both_casings_set_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEPH_SERVICE_NAME", "upper")
    monkeypatch.setenv("heph_service_name", "lower")
    assert HephSettings().service_name in {"upper", "lower"}


def test_required_name_that_is_not_a_field_is_reported() -> None:
    class Typo(HephSettings):
        required_in_prod: ClassVar[tuple[str, ...]] = ("nonexistent",)

    with pytest.raises(SettingsError) as exc:
        Typo(env="prod", service_name="x", database_url=SecretStr(SECRET))
    assert exc.value.missing == ["nonexistent"]
