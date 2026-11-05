//! Shared conformance-vector loading for every `conformance_*.rs` test.
#![allow(dead_code)]

use hephkit_core::CoreError;
use serde::Deserialize;
use serde_json::{value::RawValue, Value};
use std::collections::HashMap;
use std::path::PathBuf;

pub struct Case {
    pub name: String,
    pub input: Value,
    pub expect: Value,
    /// Each top-level member of `input` as its original text, byte for byte.
    /// Use this to hand wire documents to the library unmodified (a
    /// `serde_json::Value` round trip would collapse duplicate keys).
    raw_members: HashMap<String, Box<RawValue>>,
}

impl Case {
    /// Original text of `input.<member>`. Panics if the member is absent, so a
    /// malformed vector fails loudly instead of passing as a rejection.
    pub fn raw(&self, member: &str) -> &str {
        self.raw_members
            .get(member)
            .unwrap_or_else(|| panic!("{}: input has no member {member:?}", self.name))
            .get()
    }

    /// Like [`Case::raw`], additionally requiring the member to be a JSON object.
    pub fn raw_object(&self, member: &str) -> &str {
        let raw = self.raw(member);
        assert!(
            raw.trim_start().starts_with('{'),
            "{}: input.{member} must be a JSON object, got {raw}",
            self.name
        );
        raw
    }
}

#[derive(Deserialize)]
struct RawFile {
    cases: Vec<RawCase>,
}

#[derive(Deserialize)]
struct RawCase {
    name: String,
    input: Box<RawValue>,
    expect: Value,
}

fn conformance_dir(area: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../conformance")
        .join(area)
}

/// Loads `conformance/<area>/<suite>.json` and returns its cases.
pub fn load(area: &str, suite: &str) -> Vec<Case> {
    let path = conformance_dir(area).join(format!("{suite}.json"));
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    let file: RawFile = serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("cannot parse {}: {e}", path.display()));
    assert!(!file.cases.is_empty(), "{} has no cases", path.display());
    file.cases
        .into_iter()
        .map(|c| Case {
            input: serde_json::from_str(c.input.get()).expect("input is JSON"),
            raw_members: serde_json::from_str(c.input.get()).unwrap_or_default(),
            name: c.name,
            expect: c.expect,
        })
        .collect()
}

/// Fails if `conformance/<area>/` holds a `*.json` suite that `suites` does not
/// list, so a new vector file can never go silently untested.
pub fn assert_suites_covered(area: &str, suites: &[&str]) {
    let dir = conformance_dir(area);
    let mut on_disk: Vec<String> = std::fs::read_dir(&dir)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", dir.display()))
        .filter_map(|entry| {
            let path = entry.expect("dir entry").path();
            (path.extension()? == "json").then(|| path.file_stem()?.to_str().map(String::from))?
        })
        .collect();
    on_disk.sort();
    let mut listed: Vec<String> = suites.iter().map(|s| s.to_string()).collect();
    listed.sort();
    assert_eq!(
        on_disk, listed,
        "conformance/{area}/*.json and the suites this test runs differ"
    );
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
