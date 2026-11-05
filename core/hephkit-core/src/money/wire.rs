//! Wire format (spec 3.1 to 3.4): `{"amount": "<minor units>", "currency": "XXX"}`.

use super::{invalid, Money};
use crate::json::{self, Json};
use crate::{CoreError, Currency};

pub(super) fn from_wire_json(json: &str) -> Result<Money, CoreError> {
    // The shared strict reader rejects duplicate member names (spec 4.3), which
    // a `serde_json::Value` round trip would silently collapse.
    let value = json::parse(json).map_err(invalid)?;
    let Json::Object(members) = value else {
        return Err(invalid("money must be a JSON object"));
    };
    if members.len() != 2 {
        return Err(invalid("money must have exactly amount and currency"));
    }
    let member = |name: &str| members.iter().find(|(n, _)| n == name).map(|(_, v)| v);
    let Some(Json::Str(amount)) = member("amount") else {
        return Err(invalid("amount must be a JSON string"));
    };
    let Some(Json::Str(currency)) = member("currency") else {
        return Err(invalid("currency must be a JSON string"));
    };
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
            r#"{"amount":"1","amount":"2","currency":"USD"}"#,
            r#"{"amount":"1","currency":"USD","currency":"USD"}"#,
        ] {
            let err = Money::from_wire_json(bad).unwrap_err();
            assert_eq!(err.code(), "HEPH-MONEY-422", "{bad}");
        }
    }
}
