//! Shared conformance-vector loading for every `conformance_*.rs` test.
#![allow(dead_code)]

use hephkit_core::CoreError;
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

pub fn minor_str(v: &Value) -> i64 {
    v.as_str().expect("minor string").parse().expect("i64")
}
