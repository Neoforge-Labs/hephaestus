use super::invalid;
use crate::CoreError;

/// Normative exponent table: `conformance/money/currency.json` (spec 3.3).
const TABLE: [([u8; 3], u8); 19] = [
    (*b"USD", 2),
    (*b"EUR", 2),
    (*b"GBP", 2),
    (*b"KES", 2),
    (*b"TZS", 2),
    (*b"NGN", 2),
    (*b"ZAR", 2),
    (*b"UGX", 0),
    (*b"JPY", 0),
    (*b"BHD", 3),
    (*b"KWD", 3),
    (*b"OMR", 3),
    (*b"KRW", 0),
    (*b"ISK", 0),
    (*b"XOF", 0),
    (*b"JOD", 3),
    (*b"CLF", 4),
    (*b"CHF", 2),
    (*b"CNY", 2),
];

/// An ISO 4217 currency with a defined minor-unit exponent.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Currency {
    pub code: [u8; 3],
    pub exponent: u8,
}

impl Currency {
    /// Looks `code` up in the table; unknown or exponent-less codes are
    /// `HEPH-MONEY-422`.
    pub fn from_code(code: &str) -> Result<Currency, CoreError> {
        TABLE
            .iter()
            .find(|(c, _)| c.as_slice() == code.as_bytes())
            .map(|&(code, exponent)| Currency { code, exponent })
            .ok_or_else(|| invalid("unknown currency or currency without a minor-unit exponent"))
    }

    pub(crate) fn as_str(&self) -> &str {
        // Table codes are ASCII; the fallback is unreachable but keeps this total.
        std::str::from_utf8(&self.code).unwrap_or("???")
    }
}
