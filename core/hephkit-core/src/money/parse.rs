use super::{invalid, Money, Rounding};
use crate::{CoreError, Currency};
use std::cmp::Ordering;

pub(super) fn parse(s: &str, currency: Currency, rounding: Rounding) -> Result<Money, CoreError> {
    let bytes = s.as_bytes();
    let (negative, rest) = match bytes.split_first() {
        Some((b'-', rest)) => (true, rest),
        _ => (false, bytes),
    };
    let (int, frac) = match rest.iter().position(|&b| b == b'.') {
        Some(i) => (&rest[..i], Some(&rest[i + 1..])),
        None => (rest, None),
    };
    let all_digits = |d: &[u8]| !d.is_empty() && d.iter().all(u8::is_ascii_digit);
    if !all_digits(int) || frac.is_some_and(|f| !all_digits(f)) {
        return Err(invalid("amount is not a plain decimal number"));
    }
    let frac = frac.unwrap_or(&[]);

    let exp = usize::from(currency.exponent);
    let (kept_frac, excess) = frac.split_at(frac.len().min(exp));
    if !excess.is_empty() && rounding == Rounding::Reject {
        return Err(invalid("more fractional digits than the currency allows"));
    }

    // Digits of the magnitude in minor units, accumulated with overflow checks.
    let mut magnitude: u128 = 0;
    let padding = exp - kept_frac.len();
    let digits = int
        .iter()
        .chain(kept_frac)
        .copied()
        .chain(std::iter::repeat_n(b'0', padding));
    for d in digits {
        magnitude = magnitude
            .checked_mul(10)
            .and_then(|m| m.checked_add(u128::from(d - b'0')))
            .ok_or_else(too_large)?;
    }

    if round_away(rounding, excess, magnitude) {
        magnitude = magnitude.checked_add(1).ok_or_else(too_large)?;
    }

    let minor = if negative {
        i64::try_from(-i128::try_from(magnitude).map_err(|_| too_large())?)
    } else {
        i64::try_from(magnitude)
    }
    .map_err(|_| too_large())?;
    Ok(Money::new(minor, currency))
}

/// Whether the truncated magnitude must be incremented, given the dropped digits.
fn round_away(rounding: Rounding, excess: &[u8], kept: u128) -> bool {
    if excess.is_empty() {
        return false;
    }
    // Compare the dropped fraction with one half.
    let half = match excess[0].cmp(&b'5') {
        Ordering::Less => Ordering::Less,
        Ordering::Greater => Ordering::Greater,
        Ordering::Equal if excess[1..].iter().any(|&d| d != b'0') => Ordering::Greater,
        Ordering::Equal => Ordering::Equal,
    };
    match rounding {
        Rounding::Reject | Rounding::Down => false,
        Rounding::HalfUp => half != Ordering::Less,
        Rounding::HalfEven => {
            half == Ordering::Greater || (half == Ordering::Equal && kept % 2 == 1)
        }
    }
}

fn too_large() -> CoreError {
    invalid("amount does not fit in 64-bit minor units")
}
