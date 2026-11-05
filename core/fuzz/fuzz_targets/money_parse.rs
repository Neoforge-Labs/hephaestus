#![no_main]

use hephkit_core::{Currency, Money, Rounding};
use libfuzzer_sys::fuzz_target;

const CURRENCIES: [&str; 4] = ["JPY", "USD", "KWD", "CLF"];
const ROUNDINGS: [Rounding; 4] = [
    Rounding::Reject,
    Rounding::HalfUp,
    Rounding::HalfEven,
    Rounding::Down,
];

fuzz_target!(|data: &[u8]| {
    let Some((&selector, rest)) = data.split_first() else {
        return;
    };
    let Ok(text) = std::str::from_utf8(rest) else {
        return;
    };
    let Ok(currency) = Currency::from_code(CURRENCIES[usize::from(selector) % 4]) else {
        return;
    };
    let rounding = ROUNDINGS[usize::from(selector >> 2) % 4];

    if let Ok(money) = Money::parse(text, currency, rounding) {
        // Whatever parsed must survive a format/parse round trip exactly.
        let again = Money::parse(&money.to_decimal_string(), currency, Rounding::Reject);
        assert_eq!(again, Ok(money));
    }
});
