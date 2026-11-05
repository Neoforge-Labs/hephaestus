//! Canonical JSON (RFC 8785), content hashes and UUIDv7 (spec section 4).

use crate::json::{self, Json};
use crate::CoreError;
use sha2::{Digest, Sha256};
use std::fmt::Write;

const VALIDATION_CODE: &str = "HEPH-VAL-422";

fn invalid(message: &str) -> CoreError {
    CoreError::Hashing {
        code: VALIDATION_CODE,
        message: message.to_string(),
    }
}

/// RFC 8785 canonical form of `json`. Number handling follows spec 4.3.
pub fn canonical_json(json: &str) -> Result<String, CoreError> {
    let value = json::parse(json).map_err(invalid)?;
    let mut out = String::with_capacity(json.len());
    write_value(&value, &mut out);
    Ok(out)
}

/// `sha256:` + lowercase hex SHA-256 over the canonical form of `json` (spec 4.2).
pub fn content_hash_json(json: &str) -> Result<String, CoreError> {
    Ok(content_hash_bytes(canonical_json(json)?.as_bytes()))
}

/// `sha256:` + lowercase hex SHA-256 of `bytes`.
pub fn content_hash_bytes(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(7 + 64);
    out.push_str("sha256:");
    for byte in digest {
        // Writing to a String cannot fail.
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// A new UUIDv7, lowercase and hyphenated. Ids are time-ordered and strictly
/// increasing within one process, including within a single millisecond.
pub fn new_uuid7() -> String {
    uuid::Uuid::now_v7().hyphenated().to_string()
}

fn write_value(value: &Json, out: &mut String) {
    match value {
        Json::Null => out.push_str("null"),
        Json::Bool(true) => out.push_str("true"),
        Json::Bool(false) => out.push_str("false"),
        Json::Int(i) => {
            let _ = write!(out, "{i}");
        }
        Json::Float(f) => write_double(*f, out),
        Json::Str(s) => write_string(s, out),
        Json::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_value(item, out);
            }
            out.push(']');
        }
        Json::Object(members) => {
            // Already sorted by UTF-16 code units and free of duplicates.
            out.push('{');
            for (i, (name, item)) in members.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_string(name, out);
                out.push(':');
                write_value(item, out);
            }
            out.push('}');
        }
    }
}

fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\u{c}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// ECMAScript `Number::toString(10)` for a finite double (RFC 8785 3.2.2.3).
fn write_double(f: f64, out: &mut String) {
    debug_assert!(f.is_finite(), "the parser only admits finite doubles");
    if f == 0.0 {
        out.push('0'); // also folds -0
        return;
    }
    if f < 0.0 {
        out.push('-');
    }
    let (digits, exp) = shortest_digits(f.abs());
    let k = digits.len() as i32;
    let n = exp + 1; // position of the decimal point relative to the digits

    if k <= n && n <= 21 {
        out.push_str(&digits);
        out.extend(std::iter::repeat_n('0', (n - k) as usize));
    } else if 0 < n && n <= 21 {
        let (int, frac) = digits.split_at(n as usize);
        out.push_str(int);
        out.push('.');
        out.push_str(frac);
    } else if -6 < n && n <= 0 {
        out.push_str("0.");
        out.extend(std::iter::repeat_n('0', (-n) as usize));
        out.push_str(&digits);
    } else {
        let (first, rest) = digits.split_at(1);
        out.push_str(first);
        if !rest.is_empty() {
            out.push('.');
            out.push_str(rest);
        }
        let e = n - 1;
        let _ = write!(out, "e{}{}", if e < 0 { '-' } else { '+' }, e.abs());
    }
}

/// Shortest decimal digits that round-trip `f` (positive, finite), and the
/// decimal exponent of the first digit. Where two shortest candidates are
/// equally close, ECMAScript picks the one with an even last digit.
fn shortest_digits(f: f64) -> (String, i32) {
    let (digits, exp) = split_sci(&format!("{f:e}"));
    if let Some(fixed) = even_tie(f, &digits, exp) {
        return (fixed, exp);
    }
    (digits, exp)
}

/// `d.ddde<exp>` into (`ddd`, exp). Only ever fed this crate's own `{:e}`
/// output, never user text, so a malformed value is a bug, not an input error.
fn split_sci(sci: &str) -> (String, i32) {
    let (mantissa, exp) = sci
        .split_once('e')
        .expect("Rust {:e} always emits d.dddde<exp>");
    (
        mantissa.chars().filter(|c| *c != '.').collect(),
        exp.parse().expect("Rust {:e} always emits d.dddde<exp>"),
    )
}

/// Number of fractional bits of `f`: the `e` in `f = odd / 2^e` (0 for an integer).
fn fractional_bits(f: f64) -> i32 {
    let bits = f.to_bits();
    let biased = ((bits >> 52) & 0x7ff) as i32;
    let fraction = bits & ((1u64 << 52) - 1);
    let (significand, exponent) = if biased == 0 {
        (fraction, -1074) // subnormal
    } else {
        (fraction | (1u64 << 52), biased - 1075)
    };
    if significand == 0 {
        return 0;
    }
    (-(exponent + significand.trailing_zeros() as i32)).max(0)
}

/// Rust breaks an exact tie between two shortest candidates upwards; ECMAScript
/// breaks it towards the even last digit (RFC 8785 appendix B:
/// 1424953923781206.2). Returns the corrected digits when that differs.
fn even_tie(f: f64, digits: &str, exp: i32) -> Option<String> {
    let last = digits.as_bytes().last()?.wrapping_sub(b'0');
    if last.is_multiple_of(2) {
        return None;
    }
    // A tie means f is exactly the midpoint of two k-digit decimals, i.e. its
    // exact decimal expansion has k+1 significant digits and ends in 5. A
    // double odd/2^e (e >= 2) has exactly e fractional decimal digits, so the
    // expansion has k+1 digits iff e == k - exp. This integer test rejects
    // nearly every input, so the exact expansion below runs only for genuine
    // ties and is never an input-controlled cost.
    let k = digits.len();
    let e = fractional_bits(f);
    if e < 2 || e != k as i32 - exp {
        return None;
    }
    // k+1 significant digits is the exact value, no rounding involved.
    let (exact, exact_exp) = split_sci(&format!("{f:.k$e}"));
    if exact_exp != exp || !exact.ends_with('5') {
        return None; // unreachable for a true tie; keeps the function total
    }
    let lower: u64 = exact[..k].parse().ok()?;
    let chosen = if lower.is_multiple_of(2) {
        lower
    } else {
        lower + 1
    };
    // `lower + 1` carrying into a new digit changes the length: not a k-digit
    // candidate, so leave Rust's answer alone.
    let candidate = format!("{chosen}");
    if candidate.len() != k || candidate == digits {
        return None;
    }
    let back: f64 = format!("{}e{}", candidate, exp - (k as i32 - 1))
        .parse()
        .ok()?;
    (back == f).then_some(candidate)
}

#[cfg(test)]
mod tests {
    use super::write_double;

    fn fmt(f: f64) -> String {
        let mut s = String::new();
        write_double(f, &mut s);
        s
    }

    // Expected strings are ECMAScript Number::toString results (RFC 8785
    // appendix B and the well-known boundary cases), not our own output.
    #[test]
    fn matches_ecmascript_number_to_string() {
        for (f, want) in [
            (0.0, "0"),
            (-0.0, "0"),
            (1.0, "1"),
            (-1.5, "-1.5"),
            (0.1, "0.1"),
            (1e21, "1e+21"),
            (1e20, "100000000000000000000"),
            (123456789012345680000.0, "123456789012345680000"),
            (0.000001, "0.000001"),
            (1e-7, "1e-7"),
            (5e-324, "5e-324"),
            (f64::MAX, "1.7976931348623157e+308"),
            (1424953923781206.2, "1424953923781206.2"),
        ] {
            assert_eq!(fmt(f), want, "{f:?}");
        }
    }

    #[test]
    fn exact_ties_take_the_even_digit() {
        // 0.5 is exact in one digit and needs no correction.
        assert_eq!(fmt(0.5), "0.5");
        // 1424953923781206.25 is exactly representable: ...206.2 and ...206.3
        // are both 0.05 away, and ECMAScript prints the even one.
        assert_eq!(fmt(1_424_953_923_781_206.0 + 0.25), "1424953923781206.2");
    }
}
