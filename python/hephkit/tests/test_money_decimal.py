"""Decimal ergonomics, immutability, errors and edge cases for hephkit.money."""

import pickle
from decimal import Decimal

import pytest

from hephkit.money import Money, MoneyError


def test_from_decimal_exact() -> None:
    assert Money.from_decimal(Decimal("5000.00"), "KES").minor == 500000


def test_from_decimal_excess_precision_rejected() -> None:
    with pytest.raises(MoneyError) as exc:
        Money.from_decimal(Decimal("0.005"), "KES")
    assert exc.value.code == "HEPH-MONEY-422"


def test_from_decimal_half_up() -> None:
    assert Money.from_decimal(Decimal("0.005"), "KES", "half_up").minor == 1


def test_to_decimal_exact() -> None:
    assert Money.parse("10.20", "KES").to_decimal() == Decimal("10.20")
    assert str(Money.parse("10.20", "KES").to_decimal()) == "10.20"


@pytest.mark.parametrize("bad", [0.005, 1.5, 5000.0, 1, "10.20", None])
def test_from_decimal_rejects_non_decimal(bad: object) -> None:
    with pytest.raises(TypeError):
        Money.from_decimal(bad, "KES")  # type: ignore[arg-type]


def test_float_never_accepted_anywhere() -> None:
    with pytest.raises(TypeError):
        Money.parse(10.2, "KES")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(10.0, "KES")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(1, "KES").allocate([1.0, 2.0])  # type: ignore[list-item]


# Decimal edge cases (see the task report for the stated behaviour).
def test_decimal_positive_exponent() -> None:
    assert Money.from_decimal(Decimal("1E+3"), "KES").minor == 100000
    assert Money.from_decimal(Decimal("1.20E+3"), "KES").minor == 120000


def test_decimal_negative_zero() -> None:
    m = Money.from_decimal(Decimal("-0"), "KES")
    assert m.minor == 0
    assert str(m) == "KES 0.00"


def test_decimal_trailing_zero_excess_is_excess_precision() -> None:
    # Spec 3.6: digit count, not value, decides. KES allows two fractional digits.
    with pytest.raises(MoneyError) as exc:
        Money.from_decimal(Decimal("0.000"), "KES")
    assert exc.value.code == "HEPH-MONEY-422"
    assert Money.from_decimal(Decimal("0.000"), "KES", "down").minor == 0


def test_decimal_fifty_digits_overflows_cleanly() -> None:
    with pytest.raises(MoneyError) as exc:
        Money.from_decimal(Decimal("1" * 50), "KES")
    assert exc.value.code == "HEPH-MONEY-422"


def test_decimal_huge_exponent_is_rejected_without_building_the_digits() -> None:
    for text in ("1E+999999999", "1E+999999999999999999"):
        with pytest.raises(MoneyError, match="too large to render") as exc:
            Money.from_decimal(Decimal(text), "KES")
        assert exc.value.code == "HEPH-MONEY-422"
    with pytest.raises(MoneyError) as exc:
        Money.from_decimal(Decimal("9E+99"), "KES")  # renders fine; core overflow
    assert exc.value.code == "HEPH-MONEY-422"


def test_decimal_huge_zero_exponent_is_zero() -> None:
    assert Money.from_decimal(Decimal("0E+999999999"), "JPY").minor == 0


def test_decimal_tiny_exponent_is_excess_precision_not_memory() -> None:
    for text in ("1E-999999999", "1E-999999999999999999"):
        with pytest.raises(MoneyError, match="too large to render") as exc:
            Money.from_decimal(Decimal(text), "KES")
        assert exc.value.code == "HEPH-MONEY-422"
        with pytest.raises(MoneyError, match="too large to render"):
            Money.from_decimal(Decimal(text), "KES", "half_up")  # rejected, not 0


@pytest.mark.parametrize("text", ["NaN", "-NaN", "sNaN", "Infinity", "-Infinity"])
def test_decimal_non_finite_rejected(text: str) -> None:
    with pytest.raises(MoneyError) as exc:
        Money.from_decimal(Decimal(text), "KES")
    assert exc.value.code == "HEPH-MONEY-422"


def test_decimal_independent_of_ambient_context() -> None:
    import decimal

    with decimal.localcontext() as ctx:
        ctx.prec = 3
        assert Money.from_decimal(Decimal("12345.67"), "KES").minor == 1234567


def test_i64_extremes_and_out_of_range() -> None:
    assert Money(2**63 - 1, "KES").minor == 2**63 - 1
    assert Money(-(2**63), "KES").minor == -(2**63)
    for bad in (2**63, -(2**63) - 1, 10**40):
        with pytest.raises(MoneyError, match="signed 64-bit range") as exc:
            Money(bad, "KES")
        assert exc.value.code == "HEPH-MONEY-422"


def test_overflow_and_mismatch_codes() -> None:
    with pytest.raises(MoneyError) as exc:
        Money(2**63 - 1, "KES") + Money(1, "KES")
    assert exc.value.code == "HEPH-MONEY-422"
    with pytest.raises(MoneyError) as exc:
        -Money(-(2**63), "KES")
    assert exc.value.code == "HEPH-MONEY-422"
    with pytest.raises(MoneyError) as exc:
        Money(1, "KES") - Money(1, "USD")
    assert exc.value.code == "HEPH-MONEY-409"


def test_allocate_bad_ratios() -> None:
    m = Money(100, "KES")
    for ratios in ([], [0, 0]):
        with pytest.raises(MoneyError) as exc:
            m.allocate(ratios)
        assert exc.value.code == "HEPH-MONEY-422"
    for ratios in ([True, True], [1, False]):
        with pytest.raises(TypeError, match="not bool"):
            m.allocate(ratios)
    for ratios in ([-1, 2], [2**64]):
        with pytest.raises(MoneyError, match="unsigned 64-bit range") as exc:
            m.allocate(ratios)
        assert exc.value.code == "HEPH-MONEY-422"


def test_unknown_currency_and_rounding() -> None:
    with pytest.raises(MoneyError) as exc:
        Money.parse("1", "XXX")
    assert exc.value.code == "HEPH-MONEY-422"
    with pytest.raises(ValueError, match="rounding"):
        Money.parse("1", "KES", "ceiling")  # type: ignore[arg-type]


def test_immutable_hashable_and_eq() -> None:
    m = Money(1020, "KES")
    with pytest.raises(AttributeError):
        m.minor = 5  # type: ignore[misc]
    with pytest.raises(AttributeError):
        m.currency = "USD"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        m.extra = 1  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        del m.minor  # type: ignore[misc]
    assert hash(m) == hash(Money(1020, "KES"))
    assert {m, Money(1020, "KES")} == {m}
    assert m == Money(1020, "KES")
    assert m != Money(1020, "USD")  # a different currency is unequal, not an error
    assert m != Money(1021, "KES")
    assert m != 1020
    assert (m == "KES 10.20") is False
    assert str(m) == "KES 10.20"
    assert repr(m) == "Money(minor=1020, currency='KES')"
    assert pickle.loads(pickle.dumps(m)) == m


def test_operators_with_foreign_types() -> None:
    m = Money(1, "KES")
    with pytest.raises(TypeError):
        m + 1  # type: ignore[operator]
    with pytest.raises(TypeError):
        m - 1.0  # type: ignore[operator]


def test_wire_shapes() -> None:
    assert Money(1020, "KES").to_wire() == {"amount": "1020", "currency": "KES"}
    assert Money.from_wire({"amount": "-5", "currency": "USD"}) == Money(-5, "USD")
    for bad in (
        {"amount": 1020, "currency": "KES"},
        {"amount": "01", "currency": "KES"},
        {"amount": "1"},
        {"amount": "1", "currency": "KES", "x": "y"},
        {},
    ):
        with pytest.raises(MoneyError) as exc:
            Money.from_wire(bad)  # type: ignore[arg-type]
        assert exc.value.code == "HEPH-MONEY-422"


def test_bool_is_not_minor_units() -> None:
    with pytest.raises(TypeError):
        Money(True, "KES")
