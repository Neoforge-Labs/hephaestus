"""Hypothesis properties mirroring core/hephkit-core/tests/prop_money.rs."""

from hypothesis import given
from hypothesis import strategies as st

from hephkit.money import Money

I64_MIN = -(2**63)
I64_MAX = 2**63 - 1

minors = st.integers(min_value=I64_MIN // 2, max_value=I64_MAX // 2)
ratio_lists = st.lists(st.integers(0, 999), min_size=1, max_size=20).filter(
    lambda r: any(r)
)


@given(minor=minors, ratios=ratio_lists)
def test_allocate_preserves_total(minor: int, ratios: list[int]) -> None:
    parts = Money(minor, "KES").allocate(ratios)
    assert len(parts) == len(ratios)
    assert sum(p.minor for p in parts) == minor
    assert all(p.currency == "KES" for p in parts)


@given(minor=minors, ratios=ratio_lists)
def test_allocate_parts_differ_by_at_most_one_unit(
    minor: int, ratios: list[int]
) -> None:
    parts = Money(minor, "KES").allocate(ratios)
    total = sum(ratios)
    sign = -1 if minor < 0 else 1
    for part, r in zip(parts, ratios, strict=True):
        floor = abs(minor) * r // total
        p = part.minor * sign
        assert p in (floor, floor + 1), (p, floor)
    for i, ri in enumerate(ratios):
        for j, rj in enumerate(ratios):
            if ri == rj:
                assert abs(parts[i].minor - parts[j].minor) <= 1


@given(minor=st.integers(min_value=I64_MIN, max_value=I64_MAX))
def test_parse_format_roundtrip(minor: int) -> None:
    # One currency per exponent in the table: 0, 2, 3 and 4.
    for code in ("JPY", "USD", "KWD", "CLF"):
        text = str(Money(minor, code).to_decimal())
        assert Money.parse(text, code).minor == minor, (code, text)


@given(minor=st.integers(min_value=I64_MIN, max_value=I64_MAX))
def test_decimal_roundtrip(minor: int) -> None:
    for code in ("JPY", "USD", "KWD", "CLF"):
        m = Money(minor, code)
        assert Money.from_decimal(m.to_decimal(), code) == m


@given(minor=minors, other=minors)
def test_add_sub_inverse(minor: int, other: int) -> None:
    a, b = Money(minor, "USD"), Money(other, "USD")
    assert (a + b) - b == a
    assert a + (-a) == Money(0, "USD")


@given(minor=st.integers(min_value=I64_MIN, max_value=I64_MAX))
def test_wire_roundtrip_and_hash_consistency(minor: int) -> None:
    m = Money(minor, "KES")
    back = Money.from_wire(m.to_wire())
    assert back == m
    assert hash(back) == hash(m)
