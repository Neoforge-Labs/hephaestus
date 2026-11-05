use hephkit_core::{Currency, Money, Rounding};
use proptest::prelude::*;

fn kes() -> Currency {
    Currency::from_code("KES").unwrap()
}

fn ratios() -> impl Strategy<Value = Vec<u64>> {
    proptest::collection::vec(0u64..1000, 1..=20)
        .prop_filter("at least one non-zero", |r| r.iter().any(|&x| x != 0))
}

proptest! {
    #[test]
    fn allocate_preserves_total(minor in (i64::MIN / 2)..(i64::MAX / 2), ratios in ratios()) {
        let parts = Money::new(minor, kes()).allocate(&ratios).unwrap();
        prop_assert_eq!(parts.len(), ratios.len());
        let sum: i128 = parts.iter().map(|p| i128::from(p.minor)).sum();
        prop_assert_eq!(sum, i128::from(minor));
        prop_assert!(parts.iter().all(|p| p.currency == kes()));
    }

    #[test]
    fn allocate_parts_differ_by_at_most_one_unit_per_ratio_weight(
        minor in (i64::MIN / 2)..(i64::MAX / 2),
        ratios in ratios(),
    ) {
        let parts = Money::new(minor, kes()).allocate(&ratios).unwrap();
        let total: i128 = ratios.iter().map(|&r| i128::from(r)).sum();
        let abs = i128::from(minor).abs();
        let sign: i128 = if minor < 0 { -1 } else { 1 };
        for (part, &r) in parts.iter().zip(&ratios) {
            // Each part is its exact share rounded down or up, never further.
            let floor = abs * i128::from(r) / total;
            let p = i128::from(part.minor) * sign;
            prop_assert!(p == floor || p == floor + 1, "part {} floor {}", p, floor);
        }
        // Equal weights differ by at most one unit.
        for (i, &ri) in ratios.iter().enumerate() {
            for (j, &rj) in ratios.iter().enumerate() {
                if ri == rj {
                    prop_assert!((parts[i].minor - parts[j].minor).abs() <= 1);
                }
            }
        }
    }

    #[test]
    fn cmp_agrees_with_minor_units_over_the_whole_range(a in any::<i64>(), b in any::<i64>()) {
        let (x, y) = (Money::new(a, kes()), Money::new(b, kes()));
        // Ordering is the i64 ordering, for every pair including i64::MIN
        // against i64::MAX, where the difference does not fit in an i64.
        prop_assert_eq!(x.checked_cmp(&y).unwrap(), a.cmp(&b));
        prop_assert_eq!(y.checked_cmp(&x).unwrap(), b.cmp(&a));
    }

    #[test]
    fn cmp_across_currencies_is_always_a_mismatch(a in any::<i64>(), b in any::<i64>()) {
        let usd = Currency::from_code("USD").unwrap();
        let (x, y) = (Money::new(a, kes()), Money::new(b, usd));
        prop_assert_eq!(x.checked_cmp(&y).unwrap_err().code(), "HEPH-MONEY-409");
        prop_assert_eq!(y.checked_cmp(&x).unwrap_err().code(), "HEPH-MONEY-409");
    }

    #[test]
    fn parse_format_roundtrip(minor in any::<i64>()) {
        // One currency per exponent in the table: 0, 2, 3 and 4.
        for code in ["JPY", "USD", "KWD", "CLF"] {
            let cur = Currency::from_code(code).unwrap();
            let text = Money::new(minor, cur).to_decimal_string();
            let back = Money::parse(&text, cur, Rounding::Reject).unwrap();
            prop_assert_eq!(back.minor, minor, "{} via {}", code, text);
        }
    }
}
