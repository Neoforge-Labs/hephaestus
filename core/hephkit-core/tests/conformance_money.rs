mod common;

use common::{check, load, minor_str, money_from_wire};
use hephkit_core::{CoreError, Currency, Money, Rounding};
use serde_json::{json, Value};

fn wire(m: &Money) -> Value {
    json!({
        "amount": m.minor.to_string(),
        "currency": std::str::from_utf8(&m.currency.code).unwrap(),
    })
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
            money_from_wire(&i["a"]).and_then(|a| match i["op"].as_str().unwrap() {
                "neg" => a.checked_neg(),
                op => {
                    let b = money_from_wire(&i["b"])?;
                    if op == "add" {
                        a.checked_add(&b)
                    } else {
                        a.checked_sub(&b)
                    }
                }
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
        let result = money_from_wire(&i["money"]).and_then(|m| {
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
