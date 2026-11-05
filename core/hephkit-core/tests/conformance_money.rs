mod common;

use common::{assert_suites_covered, check, load, minor_str, Case};
use hephkit_core::{CoreError, Currency, Money, Rounding};
use serde_json::Value;

/// Passes the vector's original bytes for `input.<member>` to the library: the
/// text member `<member>_text` when present (a runner MUST pass those exact
/// bytes), otherwise the raw object.
fn from_wire(c: &Case, member: &str) -> Result<Money, CoreError> {
    match c.input.get(format!("{member}_text")) {
        Some(text) => Money::from_wire_json(text.as_str().expect("_text member is a string")),
        None => Money::from_wire_json(c.raw_object(member)),
    }
}

#[test]
fn every_suite_file_is_exercised() {
    assert_suites_covered(
        "money",
        &["currency", "parse", "format", "arith", "allocate"],
    );
}

fn wire(m: &Money) -> Value {
    serde_json::from_str(&m.to_wire_json()).unwrap()
}

fn rounding(s: &str) -> Rounding {
    match s {
        "reject" => Rounding::Reject,
        "half_up" => Rounding::HalfUp,
        "half_even" => Rounding::HalfEven,
        "down" => Rounding::Down,
        other => panic!("unknown rounding {other}"),
    }
}

#[test]
fn currency() {
    for c in load("money", "currency") {
        let code = c.input["code"].as_str().unwrap();
        check(
            &c.name,
            Currency::from_code(code).map(|cur| cur.exponent),
            &c.expect,
            |e| e["exponent"].as_u64().unwrap() as u8,
        );
    }
}

#[test]
fn parse() {
    for c in load("money", "parse") {
        let i = &c.input;
        let result = Currency::from_code(i["currency"].as_str().unwrap()).and_then(|cur| {
            Money::parse(
                i["amount"].as_str().unwrap(),
                cur,
                rounding(i["rounding"].as_str().unwrap()),
            )
            .map(|m| m.minor)
        });
        check(&c.name, result, &c.expect, |e| minor_str(&e["minor"]));
    }
}

#[test]
fn format() {
    for c in load("money", "format") {
        let i = &c.input;
        let result = Currency::from_code(i["currency"].as_str().unwrap())
            .map(|cur| Money::new(minor_str(&i["minor"]), cur).to_decimal_string());
        check(&c.name, result, &c.expect, |e| {
            e["amount"].as_str().unwrap().to_string()
        });
    }
}

#[test]
fn arith() {
    for c in load("money", "arith") {
        let i = &c.input;
        let result: Result<Money, CoreError> =
            from_wire(&c, "a").and_then(|a| match i["op"].as_str().unwrap() {
                "neg" => a.checked_neg(),
                "add" => a.checked_add(&from_wire(&c, "b")?),
                "sub" => a.checked_sub(&from_wire(&c, "b")?),
                other => panic!("{}: unknown op {other}", c.name),
            });
        check(&c.name, result.map(|m| wire(&m)), &c.expect, |e| {
            e["result"].clone()
        });
    }
}

#[test]
fn allocate() {
    for c in load("money", "allocate") {
        let i = &c.input;
        let result = from_wire(&c, "money").and_then(|m| {
            let ratios: Vec<u64> = i["ratios"]
                .as_array()
                .unwrap()
                .iter()
                .map(|r| r.as_u64().unwrap())
                .collect();
            m.allocate(&ratios)
        });
        check(
            &c.name,
            result.map(|parts| Value::Array(parts.iter().map(wire).collect())),
            &c.expect,
            |e| e["parts"].clone(),
        );
    }
}
