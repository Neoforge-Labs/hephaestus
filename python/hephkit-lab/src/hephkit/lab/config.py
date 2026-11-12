"""Typed experiment configs with layered overrides and a content-hashed result.

A config is a pydantic model. :func:`resolve` builds one from four layers --
defaults, a JSON file, the environment, the command line, applied in that order
so each beats the one before it (design 8.1) -- validates the result and returns
it. :func:`config_hash` is the content hash of that result (spec 4.2), computed
by :func:`hephkit.hashing.content_hash`; nothing is hashed here.

Every refusal is a :class:`ConfigError` carrying ``HEPH-LAB-422`` and the dotted
path of the member at fault, because that code's guidance asks the caller to fix
the *layer* that supplied the bad value rather than to patch the config after
resolution. :class:`ExperimentConfig` is frozen to make that structurally true:
the object :func:`resolve` returns is the object :func:`config_hash` hashes, and
there is no later assignment to it that the hash would not see.

Conventions this module fixes, because the spec does not:

* **Environment.** Only members under the ``HEPH_`` prefix are read, so an
  unrelated environment variable is never a config value. ``__`` separates
  nesting levels: ``HEPH_OPTIM__LR`` sets ``optim.lr``.
* **Command line.** Options are ``--<dotted.path>=<value>`` or
  ``--<dotted.path> <value>``. There are no implicit booleans; write
  ``--flag=true``.
* **Scalars from the environment and the command line** are read as JSON when
  they parse as JSON and as the raw string otherwise, so ``--seed=7`` is the
  integer 7 and ``--name=resnet`` is the string ``"resnet"``. Pydantic does the
  rest of the coercion.
* **The file layer** is one JSON object. A ``file`` that does not exist is not
  this module's error to invent: :class:`OSError` propagates. The registry
  reserves ``HEPH-LAB-424`` for an absent required artefact.

Maturity: experimental.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from hephkit.hashing import content_hash
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as _ValidationError
from pydantic_core import PydanticSerializationError, to_jsonable_python

__all__ = [
    "ENV_NESTING",
    "ENV_PREFIX",
    "ConfigError",
    "ExperimentConfig",
    "config_hash",
    "resolve",
]

#: The registry code every refusal in this module carries (`spec/errors.yaml`).
CODE = "HEPH-LAB-422"

#: Environment members outside this prefix are not config values.
ENV_PREFIX = "HEPH_"

#: What separates nesting levels in an environment member name.
ENV_NESTING = "__"

C = TypeVar("C", bound=BaseModel)


class ConfigError(ValueError):
    """An experiment config does not satisfy its model (``HEPH-LAB-422``).

    ``field`` is the dotted path of the member at fault (``optim.lr``,
    ``tags[1]``) or ``None`` when the fault is not a single member, and
    ``layer`` names the layer that supplied it, so the caller can fix the layer
    rather than the resolved object.
    """

    code = CODE

    def __init__(self, message: str, *, field: str | None = None, layer: str | None = None) -> None:
        super().__init__(message)
        self.field = field
        self.layer = layer


class ExperimentConfig(BaseModel):
    """Base class for an experiment config: frozen, and closed to extras.

    Frozen because resolution is the single point at which a config comes into
    being: a value patched afterwards is not the value ``config_hash`` would
    have hashed. Closed to extras so a typo cannot ride along as a member the
    model never declared.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def _as_mapping(value: Any, layer: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise ConfigError(
        f"the {layer} config layer must be a JSON object, not {type(value).__name__}",
        layer=layer,
    )


def _leaf_paths(tree: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """Every path in `tree` at which a non-mapping value sits."""
    for key, value in tree.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping) and value:
            yield from _leaf_paths(value, path)
        else:
            yield path


def _merge(into: dict[str, Any], src: Mapping[str, Any]) -> None:
    """Deep-merge `src` over `into`: a mapping merges, anything else replaces."""
    for key, value in src.items():
        if isinstance(value, Mapping) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        elif isinstance(value, Mapping):
            nested: dict[str, Any] = {}
            _merge(nested, value)
            into[key] = nested
        else:
            into[key] = value


def _set_path(into: dict[str, Any], parts: Sequence[str], value: Any, layer: str) -> None:
    cursor = into
    for depth, part in enumerate(parts[:-1]):
        nxt = cursor.get(part)
        if nxt is None:
            nxt = cursor[part] = {}
        elif not isinstance(nxt, dict):
            dotted = ".".join(parts)
            raise ConfigError(
                f"the {layer} layer sets {dotted!r}, but an earlier layer gave "
                f"{'.'.join(parts[: depth + 1])!r} a value that is not an object",
                field=dotted,
                layer=layer,
            )
        cursor = nxt
    cursor[parts[-1]] = value


def _scalar(text: str) -> Any:
    """A value from the environment or the command line: JSON if it parses."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _check_path(model: type[BaseModel], parts: Sequence[str], layer: str) -> None:
    """Refuse a path the model does not declare, naming the whole path.

    Checking stops at the first member whose annotation is not another model:
    below a `dict[str, Any]` the model declares no structure, so there is
    nothing there to contradict.
    """
    cursor: type[BaseModel] | None = model
    for index, part in enumerate(parts):
        if cursor is None:
            return
        fields = cursor.model_fields
        if part not in fields:
            dotted = ".".join(parts[: index + 1])
            known = ", ".join(sorted(fields)) or "no members"
            raise ConfigError(
                f"the {layer} layer sets {dotted!r}, which this config does not "
                f"declare (it declares: {known})",
                field=dotted,
                layer=layer,
            )
        annotation = fields[part].annotation
        cursor = (
            annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel)
            else None
        )


def _apply(
    merged: dict[str, Any],
    origins: dict[str, str],
    model: type[BaseModel],
    layer: str,
    values: Mapping[tuple[str, ...], Any],
) -> None:
    """Set every path of one override layer, recording which layer set it."""
    for parts, value in values.items():
        _check_path(model, parts, layer)
        _set_path(merged, parts, value, layer)
        origins[".".join(parts)] = layer


def _cli_values(argv: Sequence[str]) -> dict[tuple[str, ...], Any]:
    values: dict[tuple[str, ...], Any] = {}
    pending = list(argv)
    while pending:
        token = pending.pop(0)
        if not token.startswith("--"):
            raise ConfigError(
                f"the cli layer takes --key=value options; got {token!r}", layer="cli"
            )
        name, sep, text = token[2:].partition("=")
        if not name:
            raise ConfigError(f"the cli option {token!r} names no config member", layer="cli")
        if not sep:
            if not pending or pending[0].startswith("--"):
                raise ConfigError(
                    f"the cli option {token!r} carries no value",
                    field=name,
                    layer="cli",
                )
            text = pending.pop(0)
        values[tuple(name.split("."))] = _scalar(text)
    return values


def _env_values(env: Mapping[str, str], prefix: str) -> dict[tuple[str, ...], Any]:
    return {
        tuple(key[len(prefix) :].lower().split(ENV_NESTING)): _scalar(value)
        for key, value in env.items()
        if key.startswith(prefix)
    }


def _read_file(file: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigError(
            f"the config file {file.name} is not valid JSON: {exc}", layer="file"
        ) from exc
    return _as_mapping(document, "file")


def _walk(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every leaf of a dumped config, with its dotted (and indexed) path."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def _unserialisable(cfg: BaseModel) -> tuple[str | None, Any]:
    """The path and value of the first member pydantic cannot serialise."""
    for path, value in _walk(cfg.model_dump()):
        try:
            to_jsonable_python(value)
        except (PydanticSerializationError, TypeError, ValueError):
            return path, value
    return None, None


def _refuse_unserialisable(cfg: BaseModel, exc: Exception) -> ConfigError:
    path, value = _unserialisable(cfg)
    if path is None:
        reason = f"pydantic could not serialise it to JSON ({exc})"
    else:
        reason = (
            f"member {path!r} holds {type(value).__name__}, "
            "which cannot be serialised to JSON"
        )
    return ConfigError(
        f"this config cannot be hashed: {reason}. Fix the config layer that "
        "supplied it rather than patching after resolution: a value patched "
        "after resolution is not the value that would be hashed into config_hash",
        field=path,
    )


def _jsonable(cfg: BaseModel) -> Any:
    try:
        return cfg.model_dump(mode="json")
    except (PydanticSerializationError, TypeError) as exc:
        raise _refuse_unserialisable(cfg, exc) from exc


def resolve(
    model: type[C],
    *,
    defaults: Mapping[str, Any] | None = None,
    file: Path | None = None,
    env: Mapping[str, str] | None = None,
    argv: Sequence[str] | None = None,
    env_prefix: str = ENV_PREFIX,
) -> C:
    """Resolve `model` from the four layers and return the validated config.

    Later layers beat earlier ones: defaults, then `file`, then `env`, then
    `argv` (design 8.1). Nested objects merge member by member, so an override
    of one member leaves its siblings alone. Every refusal is a
    :class:`ConfigError` naming the member and the layer.
    """
    merged: dict[str, Any] = {}
    # Dotted path -> the layer that last set it, so a validation failure can
    # name the layer to fix rather than only the member.
    origins: dict[str, str] = {}
    for layer, mapping in (
        ("defaults", defaults),
        ("file", _read_file(file) if file is not None else None),
    ):
        if mapping is None:
            continue
        tree = _as_mapping(mapping, layer)
        paths = list(_leaf_paths(tree))
        for parts in paths:
            _check_path(model, parts, layer)
        _merge(merged, tree)
        origins.update({".".join(parts): layer for parts in paths})
    _apply(merged, origins, model, "env", _env_values(env or {}, env_prefix))
    _apply(merged, origins, model, "cli", _cli_values(argv or ()))

    try:
        cfg = model.model_validate(merged)
    except _ValidationError as exc:
        first = exc.errors()[0]
        path = ".".join(str(part) for part in first["loc"])
        origin = origins.get(path)
        where = f" (set by the {origin} layer)" if origin else ""
        raise ConfigError(
            f"this config does not satisfy {model.__name__}: "
            f"{path or '<root>'}: {first['msg']}{where}",
            field=path or None,
            layer=origin,
        ) from exc
    # Resolution produces the object that gets hashed, so a config that could
    # not be hashed is refused here rather than at the hash.
    _jsonable(cfg)
    return cfg


def config_hash(cfg: BaseModel) -> str:
    """The content hash of `cfg` (spec 4.2), over its canonical JSON (spec 4.1)."""
    payload = _jsonable(cfg)
    try:
        return content_hash(payload)
    except TypeError as exc:  # pragma: no cover - mode="json" leaves no such value
        raise _refuse_unserialisable(cfg, exc) from exc
