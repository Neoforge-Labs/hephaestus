"""Money as integer minor units plus a currency (spec section 3). Experimental.

All parsing, rounding, arithmetic, comparison and wire rules live in the Rust
core, the currency-mismatch check among them (spec 3.8). This module converts
types and adds ``Decimal`` ergonomics. Floating point never touches money: a
``float`` is a ``TypeError``.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
import json
from typing import Final, Literal, cast, final

from hephkit import _core
from hephkit._core import MoneyError

__all__ = ["Money", "MoneyError", "Rounding"]

Rounding = Literal["reject", "half_up", "half_even", "down"]

# A Decimal whose plain (non-scientific) rendering would exceed this many
# characters is rejected (HEPH-MONEY-422, "too large to render") before Python
# builds a gigantic string for something like Decimal("1E+999999999999").
# Binding-level policy; see the non-normative note in spec 3.6.
_MAX_PLAIN_CHARS: Final = 4096
_TOO_LARGE_CODE: Final = _core.MONEY_INVALID_CODE


def _decimal_text(value: Decimal) -> str:
    """Plain decimal text for ``value`` (never scientific, never via ``float``).

    Trailing zeros are kept, so ``Decimal("10.290")`` keeps its three
    fractional digits; the core then accepts them because every digit beyond
    the currency's exponent is zero and the value is preserved (spec 3.6).
    A non-finite value yields text the core rejects. A value whose plain form
    would exceed ``_MAX_PLAIN_CHARS`` raises ``MoneyError``.
    """
    if not value.is_finite():
        return str(value)
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - finite implies int
        return str(value)
    if not any(digits) and exponent > 0:
        return "-0" if sign else "0"  # zero has no integer trailing zeros to spell out
    width = len(digits) + exponent if exponent >= 0 else max(len(digits), -exponent) + 2
    if width > _MAX_PLAIN_CHARS:
        err = MoneyError(
            f"{_TOO_LARGE_CODE}: decimal is too large to render "
            f"(plain form would exceed {_MAX_PLAIN_CHARS} characters)"
        )
        err.code = _TOO_LARGE_CODE
        raise err
    return format(value, "f")


@final
class Money:
    """An immutable, hashable amount of integer minor units in one currency."""

    __slots__ = ("_currency", "_minor")

    _minor: int
    _currency: str

    def __init__(self, minor: int, currency: str) -> None:
        if isinstance(minor, bool):
            raise TypeError("minor must be an int, not bool")
        checked_minor, checked_currency = _core.money_check(minor, currency)
        object.__setattr__(self, "_minor", checked_minor)
        object.__setattr__(self, "_currency", checked_currency)

    @classmethod
    def _from_core(cls, pair: tuple[int, str]) -> "Money":
        self = object.__new__(cls)
        object.__setattr__(self, "_minor", pair[0])
        object.__setattr__(self, "_currency", pair[1])
        return self

    @classmethod
    def parse(cls, amount: str, currency: str, rounding: Rounding = "reject") -> "Money":
        """Parse a human decimal string such as ``"19.99"`` (spec 3.6)."""
        return cls._from_core(_core.money_parse(amount, currency, rounding))

    @classmethod
    def from_decimal(
        cls, value: Decimal, currency: str, rounding: Rounding = "reject"
    ) -> "Money":
        """Convert a ``Decimal`` exactly; only ``Decimal`` is accepted (no ``float``, no ``int``).

        Fractional digits beyond the currency's exponent are accepted when every
        one of them is zero, so ``Decimal("5000.00")`` is 5000 JPY minor units
        (spec 3.6). A non-zero digit beyond the exponent needs ``rounding``.

        Size limit: a value whose plain (non-scientific) form would exceed 4096
        characters is rejected with ``MoneyError`` (``HEPH-MONEY-422``, "too large
        to render"), so a compact ``Decimal("1E-999999999999")`` cannot expand into
        an enormous string. Trade-off: such a value is rejected even where the core
        would round it, e.g. ``Decimal("1E-999999999")`` with ``half_up`` raises
        instead of giving 0.
        """
        if not isinstance(value, Decimal):
            raise TypeError(
                f"value must be a decimal.Decimal, not {type(value).__name__}"
            )
        return cls.parse(_decimal_text(value), currency, rounding)

    @classmethod
    def from_wire(cls, d: Mapping[str, str]) -> "Money":
        """Parse a wire object ``{"amount": "1999", "currency": "USD"}`` (spec 3.1)."""
        text = json.dumps(dict(d), ensure_ascii=True, separators=(",", ":"))
        return cls._from_core(_core.money_from_wire(text))

    @property
    def minor(self) -> int:
        return self._minor

    @property
    def currency(self) -> str:
        return self._currency

    def to_decimal(self) -> Decimal:
        return Decimal(_core.money_to_decimal(self._minor, self._currency))

    def to_wire(self) -> dict[str, str]:
        return cast(
            "dict[str, str]",
            json.loads(_core.money_to_wire(self._minor, self._currency)),
        )

    def allocate(self, ratios: Sequence[int]) -> list["Money"]:
        """Split by largest remainder, ties to the lower index (spec 3.7)."""
        parts = _core.money_allocate(self._minor, self._currency, list(ratios))
        return [Money._from_core(p) for p in parts]

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money._from_core(
            _core.money_add(self._minor, self._currency, other._minor, other._currency)
        )

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money._from_core(
            _core.money_sub(self._minor, self._currency, other._minor, other._currency)
        )

    def __neg__(self) -> "Money":
        return Money._from_core(_core.money_neg(self._minor, self._currency))

    def _cmp(self, other: "Money") -> int:
        """-1, 0 or 1 from the core (spec 3.8).

        The currency-mismatch check lives in the core, not here: this raises
        ``MoneyError`` with code ``HEPH-MONEY-409`` only because the core
        returned it.
        """
        return _core.money_cmp(
            self._minor, self._currency, other._minor, other._currency
        )

    # Ordering (spec 3.8). Each operator returns ``NotImplemented`` for a
    # non-Money operand, so ``money < 5`` is a ``TypeError`` from Python: that
    # is a programming bug, not a money-domain error, and must not be dressed
    # up as HEPH-MONEY-409. Two different currencies do raise that code.
    # ``__eq__`` is deliberately not one of these: it answers every pair, so a
    # Money stays usable as a dict key and in a set.

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._cmp(other) < 0

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._cmp(other) <= 0

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._cmp(other) > 0

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._cmp(other) >= 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._minor == other._minor and self._currency == other._currency

    def __hash__(self) -> int:
        return hash((self._minor, self._currency))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __reduce__(self) -> tuple[type["Money"], tuple[int, str]]:
        return (Money, (self._minor, self._currency))

    def __str__(self) -> str:
        return f"{self._currency} {_core.money_to_decimal(self._minor, self._currency)}"

    def __repr__(self) -> str:
        return f"Money(minor={self._minor}, currency={self._currency!r})"
