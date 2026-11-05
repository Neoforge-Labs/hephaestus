//! Wire format (spec 3.1 to 3.4): `{"amount": "<minor units>", "currency": "XXX"}`.

use super::{invalid, Money};
use crate::{CoreError, Currency};
use serde_json::Value;

pub(super) fn from_wire_json(json: &str) -> Result<Money, CoreError> {
    let value: Value = serde_json::from_str(json).map_err(|_| invalid("not valid JSON"))?;
    let obj = value
        .as_object()
        .ok_or_else(|| invalid("money must be a JSON object"))?;
    if obj.len() != 2 {
        return Err(invalid("money must have exactly amount and currency"));
    }
    let amount = obj
        .get("amount")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid("amount must be a JSON string"))?;
    let currency = obj
        .get("currency")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid("currency must be a JSON string"))?;
    Ok(Money::new(minor(amount)?, Currency::from_code(currency)?))
}

pub(super) fn to_wire_json(money: &Money) -> String {
    // Amount and currency code contain only digits, '-' and ASCII letters,
    // so no escaping is needed.
    format!(
        r#"{{"amount":"{}","currency":"{}"}}"#,
        money.minor,
        money.currency.as_str()
    )
}

/// `^(0|-?[1-9][0-9]*)$` and fits in `i64`.
fn minor(s: &str) -> Result<i64, CoreError> {
    let digits = s.strip_prefix('-').unwrap_or(s);
    let canonical = match digits.as_bytes() {
        [] => false,
        [b'0'] => s == "0",
        [first, rest @ ..] => (b'1'..=b'9').contains(first) && rest.iter().all(u8::is_ascii_digit),
    };
    if !canonical {
        return Err(invalid("amount is not a canonical integer"));
    }
    s.parse::<i64>()
        .map_err(|_| invalid("amount does not fit in 64-bit minor units"))
}

#[cfg(test)]
mod tests {
    use crate::{Currency, Money};

    #[test]
    fn round_trips() {
        let m = Money::new(-1999, Currency::from_code("USD").unwrap());
        assert_eq!(m.to_wire_json(), r#"{"amount":"-1999","currency":"USD"}"#);
        assert_eq!(Money::from_wire_json(&m.to_wire_json()), Ok(m));
    }

    #[test]
    fn rejects_malformed_documents() {
        for bad in [
            "",
            "nope",
            "[]",
            "\"x\"",
            "null",
            r#"{"amount":"1","currency":1}"#,
            r#"{"amount":"-","currency":"USD"}"#,
            r#"{"amount":"","currency":"USD"}"#,
            r#"{"amount":"-0","currency":"USD"}"#,
            r#"{"amount":"00","currency":"USD"}"#,
            r#"{"amount":"1.0","currency":"USD"}"#,
            r#"{"amount":"1","currency":"USD","x":1}"#,
        ] {
            let err = Money::from_wire_json(bad).unwrap_err();
            assert_eq!(err.code(), "HEPH-MONEY-422", "{bad}");
        }
    }
}
