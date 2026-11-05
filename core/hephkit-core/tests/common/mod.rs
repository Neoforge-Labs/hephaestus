//! Shared conformance-vector loading for every `conformance_*.rs` test.
#![allow(dead_code)]

use hephkit_core::{CoreError, Currency, Money};
use serde_json::Value;
use std::path::PathBuf;

pub struct Case {
    pub name: String,
    pub input: Value,
    pub expect: Value,
}

/// Loads `conformance/<area>/<suite>.json` and returns its cases.
pub fn load(area: &str, suite: &str) -> Vec<Case> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../conformance")
        .join(area)
        .join(format!("{suite}.json"));
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    let doc: Value = serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("cannot parse {}: {e}", path.display()));
    let cases = doc["cases"].as_array().expect("cases array");
    assert!(!cases.is_empty(), "{} has no cases", path.display());
    cases
        .iter()
        .map(|c| Case {
            name: c["name"].as_str().expect("case name").to_string(),
            input: c["input"].clone(),
            expect: c["expect"].clone(),
        })
        .collect()
}

/// Asserts `actual` against an `{"error": "<HEPH code>"}` expectation, or
/// returns the `Ok` value for the caller to compare.
pub fn check<T: PartialEq + std::fmt::Debug>(
    name: &str,
    actual: Result<T, CoreError>,
    expect: &Value,
    expected_ok: impl FnOnce(&Value) -> T,
) {
    match (actual, expect.get("error").and_then(Value::as_str)) {
        (Err(e), Some(code)) => assert_eq!(e.code(), code, "{name}: wrong error code ({e})"),
        (Ok(v), None) => assert_eq!(v, expected_ok(expect), "{name}"),
        (Ok(v), Some(code)) => panic!("{name}: expected error {code}, got Ok({v:?})"),
        (Err(e), None) => panic!("{name}: expected success, got error {e}"),
    }
}

fn wire_err(msg: &str) -> CoreError {
    CoreError::Money {
        code: "HEPH-MONEY-422",
        message: msg.to_string(),
    }
}

/// Reads a spec section 3.1 wire object: exactly `amount` (a JSON string
/// matching `^(0|-?[1-9][0-9]*)$` that fits `i64`) and `currency`.
pub fn money_from_wire(v: &Value) -> Result<Money, CoreError> {
    let obj = v.as_object().ok_or_else(|| wire_err("not an object"))?;
    if obj.len() != 2 {
        return Err(wire_err("wire object must have exactly two members"));
    }
    let amount = obj
        .get("amount")
        .and_then(Value::as_str)
        .ok_or_else(|| wire_err("amount must be a string"))?;
    let currency = obj
        .get("currency")
        .and_then(Value::as_str)
        .ok_or_else(|| wire_err("currency must be a string"))?;
    Ok(Money::new(
        wire_minor(amount)?,
        Currency::from_code(currency)?,
    ))
}

fn wire_minor(s: &str) -> Result<i64, CoreError> {
    let digits = s.strip_prefix('-').unwrap_or(s);
    let valid = !digits.is_empty()
        && digits.bytes().all(|b| b.is_ascii_digit())
        && (digits == "0" && s == "0" || !digits.starts_with('0'));
    if !valid {
        return Err(wire_err("amount is not a canonical integer"));
    }
    s.parse::<i64>()
        .map_err(|_| wire_err("amount does not fit in i64"))
}

pub fn minor_str(v: &Value) -> i64 {
    v.as_str().expect("minor string").parse().expect("i64")
}
