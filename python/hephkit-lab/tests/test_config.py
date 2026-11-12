"""`hephkit.lab.config`: layered resolution, refusals and the config hash.

The conformance vectors in `conformance/lab/config.json` pin the behaviour;
these tests cover the Python surface around it -- the error object, the frozen
resolved config, the file layer and Review Focus 1 (a value no JSON encoder can
take).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hephkit.hashing import content_hash
from hephkit.lab.config import (
    ENV_PREFIX,
    ConfigError,
    ExperimentConfig,
    MissingConfigError,
    config_hash,
    resolve,
)


class Optim(ExperimentConfig):
    lr: float
    momentum: float


class Train(ExperimentConfig):
    seed: int
    name: str
    optim: Optim


class Loose(ExperimentConfig):
    """A research config with an untyped member, which is how a NumPy scalar
    reaches a config at all: a `float` member would be coerced by pydantic."""

    lr: Any = None


class Opaque:
    """Stands in for `numpy.float32`.

    NumPy is not a dependency of the spine (ADR 0023), so the property under
    test is reproduced rather than imported: a value that neither pydantic nor
    `json.dumps` can serialise. `test_a_real_numpy_scalar_...` below runs the
    genuine article wherever NumPy happens to be installed.
    """

    def __repr__(self) -> str:  # pragma: no cover - only for failure messages
        return "Opaque()"


DEFAULTS = {"seed": 1, "name": "base", "optim": {"lr": 0.1, "momentum": 0.9}}


def test_defaults_alone_resolve() -> None:
    cfg = resolve(Train, defaults=DEFAULTS)
    assert cfg.model_dump(mode="json") == DEFAULTS


def test_precedence_cli_beats_env_beats_file_beats_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"seed": 2, "name": "from-file"}), encoding="utf-8")
    cfg = resolve(
        Train,
        defaults=DEFAULTS,
        file=path,
        env={"HEPH_SEED": "3"},
        argv=["--seed=4"],
    )
    # `seed` is contested by all four layers, `name` by two, `optim` by one.
    assert cfg.seed == 4
    assert cfg.name == "from-file"
    assert cfg.optim.lr == 0.1


def test_a_nested_override_keeps_its_siblings(tmp_path: Path) -> None:
    cfg = resolve(Train, defaults=DEFAULTS, argv=["--optim.lr=0.05"])
    assert cfg.optim.lr == 0.05
    assert cfg.optim.momentum == 0.9


def test_a_cli_option_may_carry_its_value_as_the_next_token() -> None:
    cfg = resolve(Train, defaults=DEFAULTS, argv=["--seed", "7"])
    assert cfg.seed == 7


def test_unknown_cli_key_raises_config_error_naming_the_key() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, argv=["--epochs=3"])
    assert exc.value.code == "HEPH-LAB-422"
    assert exc.value.field == "epochs"
    assert exc.value.layer == "cli"
    assert "epochs" in str(exc.value)


def test_unknown_env_key_raises_config_error_naming_the_key() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, env={"HEPH_EPOCHS": "3"})
    assert exc.value.field == "epochs"
    assert exc.value.layer == "env"


def test_unknown_nested_key_is_named_by_its_whole_path() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, argv=["--optim.decay=0.01"])
    assert exc.value.field == "optim.decay"


def test_unknown_key_in_the_defaults_layer_is_refused() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults={**DEFAULTS, "epochs": 3})
    assert exc.value.field == "epochs"
    assert exc.value.layer == "defaults"


def test_unprefixed_env_members_are_ignored() -> None:
    cfg = resolve(Train, defaults=DEFAULTS, env={"PATH": "/usr/bin", "SEED": "99"})
    assert cfg.seed == 1


def test_the_env_prefix_is_the_documented_one() -> None:
    assert ENV_PREFIX == "HEPH_"


def test_a_value_of_the_wrong_type_is_refused_naming_the_field() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, argv=["--seed=abc"])
    assert exc.value.code == "HEPH-LAB-422"
    assert exc.value.field == "seed"


def test_a_missing_member_is_refused_naming_the_field() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults={"seed": 1, "optim": {"lr": 0.1, "momentum": 0.9}})
    assert exc.value.field == "name"


def test_config_error_is_a_value_error() -> None:
    assert issubclass(ConfigError, ValueError)


def test_a_bare_cli_argument_is_refused() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, argv=["seed=4"])
    assert "seed=4" in str(exc.value)
    assert exc.value.layer == "cli"


def test_a_cli_option_with_no_name_is_refused() -> None:
    with pytest.raises(ConfigError):
        resolve(Train, defaults=DEFAULTS, argv=["--=4"])


def test_a_cli_option_with_no_value_is_refused() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, argv=["--seed"])
    assert exc.value.field == "seed"


def test_the_file_layer_must_be_a_json_object(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, file=path)
    assert exc.value.layer == "file"


def test_a_malformed_config_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, file=path)
    assert exc.value.code == "HEPH-LAB-422"
    assert exc.value.layer == "file"


def test_overriding_a_member_of_a_non_object_value_is_refused() -> None:
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults={"optim": 1, "seed": 1, "name": "base"}, argv=["--optim.lr=0.5"])
    assert exc.value.field == "optim.lr"


def test_the_resolved_config_cannot_be_patched_after_resolution() -> None:
    """HEPH-LAB-422's guidance made structural: the object `resolve` returns is
    the object `config_hash` hashes, so there is no post-resolution patch."""
    cfg = resolve(Train, defaults=DEFAULTS)
    with pytest.raises(ValueError):
        cfg.seed = 2  # type: ignore[misc]


def test_an_experiment_config_refuses_an_unknown_member() -> None:
    with pytest.raises(ValueError):
        Optim(lr=0.1, momentum=0.9, decay=0.0)  # type: ignore[call-arg]


def test_config_hash_is_the_content_hash_of_the_json_dump() -> None:
    cfg = resolve(Train, defaults=DEFAULTS)
    assert config_hash(cfg) == content_hash(cfg.model_dump(mode="json"))


def test_config_hash_is_stable_across_key_order() -> None:
    class Ab(ExperimentConfig):
        a: int
        b: int

    class Ba(ExperimentConfig):
        b: int
        a: int

    assert config_hash(Ab(a=2, b=1)) == config_hash(Ba(b=1, a=2))


def test_config_hash_accepts_a_plain_pydantic_model() -> None:
    class Plain(BaseModel):
        a: int

    assert config_hash(Plain(a=1)) == content_hash({"a": 1})


def test_numpy_scalar_in_config_raises_config_error_naming_the_field() -> None:
    """Review Focus 1: a raw `TypeError` from the JSON encoder is the wrong
    answer, because it does not say which field is at fault."""
    cfg = Loose.model_construct(lr=Opaque())
    with pytest.raises(ConfigError) as exc:
        config_hash(cfg)
    assert exc.value.code == "HEPH-LAB-422"
    assert exc.value.field == "lr"
    assert "lr" in str(exc.value)
    assert "Opaque" in str(exc.value)


def test_an_unserialisable_value_nested_in_a_mapping_is_named_by_its_path() -> None:
    class Holder(ExperimentConfig):
        params: dict[str, Any] = {}

    cfg = Holder.model_construct(params={"lr": Opaque()})
    with pytest.raises(ConfigError) as exc:
        config_hash(cfg)
    assert exc.value.field == "params.lr"


def test_an_unserialisable_value_in_a_sequence_is_named_by_its_index() -> None:
    class Holder(ExperimentConfig):
        tags: list[Any] = []

    cfg = Holder.model_construct(tags=["a", Opaque()])
    with pytest.raises(ConfigError) as exc:
        config_hash(cfg)
    assert exc.value.field == "tags[1]"


def test_resolve_refuses_a_config_it_would_not_be_able_to_hash() -> None:
    """Resolution produces the object that gets hashed, so a value that cannot
    be hashed is refused at the layer that supplied it, not at the hash."""
    with pytest.raises(ConfigError) as exc:
        resolve(Loose, defaults={"lr": Opaque()})
    assert exc.value.field == "lr"


def test_a_real_numpy_scalar_is_refused_the_same_way() -> None:
    numpy = pytest.importorskip("numpy", reason="NumPy is not a spine dependency")
    cfg = Loose.model_construct(lr=numpy.float32(0.1))
    with pytest.raises(ConfigError) as exc:
        config_hash(cfg)
    assert exc.value.field == "lr"
    # An array as well as a scalar: `_walk` treats `list` and `tuple` as
    # containers and deliberately does not reach inside an ndarray, so the
    # array is one leaf and must be named as one rather than walked into.
    with pytest.raises(ConfigError) as arr:
        config_hash(Loose.model_construct(lr=numpy.array([1, 2])))
    assert arr.value.field == "lr"


def test_the_codes_are_the_generated_registry_constants() -> None:
    """CLAUDE.md: error codes live only in `spec/errors.yaml`. Nothing else on
    this branch would catch a code hand-spelled in module source."""
    from hephkit.errors import LAB_422, LAB_424

    assert ConfigError.code is LAB_422
    assert MissingConfigError.code is LAB_424


def test_a_nested_object_replaces_a_scalar_from_an_earlier_layer(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"optim": {"lr": 0.2, "momentum": 0.8}}), encoding="utf-8")
    cfg = resolve(Train, defaults={"seed": 1, "name": "base", "optim": 1}, file=path)
    assert cfg.optim.lr == 0.2


def test_a_path_below_an_untyped_member_is_not_checked_against_the_model() -> None:
    class Holder(ExperimentConfig):
        params: dict[str, Any] = {}

    cfg = resolve(Holder, argv=["--params.anything.at.all=1"])
    assert cfg.params == {"anything": {"at": {"all": 1}}}


def test_a_serialiser_that_fails_only_in_json_mode_is_still_a_config_error() -> None:
    """The fallback for a config pydantic refuses without one member to blame."""
    from pydantic import field_serializer

    class Awkward(ExperimentConfig):
        lr: float

        @field_serializer("lr", when_used="json")
        def _fail(self, value: float) -> float:
            raise RuntimeError("no json for you")

    with pytest.raises(ConfigError) as exc:
        config_hash(Awkward(lr=0.1))
    assert exc.value.code == "HEPH-LAB-422"
    assert exc.value.field is None


def test_the_file_layer_merges_into_a_nested_object_member_by_member(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"optim": {"lr": 0.2}}), encoding="utf-8")
    cfg = resolve(Train, defaults=DEFAULTS, file=path)
    assert (cfg.optim.lr, cfg.optim.momentum) == (0.2, 0.9)


def test_a_wrong_type_names_the_layer_that_set_it(tmp_path: Path) -> None:
    """HEPH-LAB-422's guidance asks for the layer, so the refusal carries it."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"seed": "abc"}), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, file=path)
    assert (exc.value.field, exc.value.layer) == ("seed", "file")
    with pytest.raises(ConfigError) as cli:
        resolve(Train, defaults=DEFAULTS, argv=["--seed=abc"])
    assert (cli.value.field, cli.value.layer) == ("seed", "cli")


def test_a_config_file_that_does_not_exist_is_heph_lab_424(tmp_path: Path) -> None:
    """`spec/errors.yaml` settles this: HEPH-LAB-422's guidance says "a config
    file that is absent rather than wrong is HEPH-LAB-424"."""
    path = tmp_path / "absent.json"
    with pytest.raises(MissingConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, file=path)
    assert exc.value.code == "HEPH-LAB-424"
    assert exc.value.layer == "file"
    assert "absent.json" in str(exc.value)


def test_a_missing_config_file_is_still_caught_as_a_config_error(tmp_path: Path) -> None:
    """One `except ConfigError` catches every refusal of this module; `.code`
    is what distinguishes the absent file from the malformed one."""
    assert issubclass(MissingConfigError, ConfigError)
    with pytest.raises(ConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, file=tmp_path / "absent.json")
    assert exc.value.code == "HEPH-LAB-424"
    assert ConfigError.code == "HEPH-LAB-422"


def test_a_directory_in_place_of_a_config_file_is_also_424(tmp_path: Path) -> None:
    with pytest.raises(MissingConfigError) as exc:
        resolve(Train, defaults=DEFAULTS, file=tmp_path)
    assert exc.value.code == "HEPH-LAB-424"


def test_a_repeated_cli_option_takes_its_last_value() -> None:
    cfg = resolve(Train, defaults=DEFAULTS, argv=["--seed=2", "--seed=3"])
    assert cfg.seed == 3


def test_a_missing_file_is_reported_before_a_bad_member_in_another_layer(
    tmp_path: Path,
) -> None:
    """424 before 422: a layer that cannot be read at all comes first."""
    with pytest.raises(MissingConfigError) as exc:
        resolve(
            Train,
            defaults={**DEFAULTS, "epochs": 3},
            file=tmp_path / "absent.json",
        )
    assert exc.value.code == "HEPH-LAB-424"
