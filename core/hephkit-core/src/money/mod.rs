//! Money as integer minor units plus a currency (spec section 3).

mod allocate;
mod currency;
mod currency_table;
mod parse;
mod wire;

pub use currency::Currency;

use crate::CoreError;

const INVALID: &str = "HEPH-MONEY-422";
const MISMATCH: &str = "HEPH-MONEY-409";

pub(crate) fn invalid(message: impl Into<String>) -> CoreError {
    CoreError::Money {
        code: INVALID,
        message: message.into(),
    }
}

/// How `Money::parse` treats input whose fractional digits beyond the
/// currency's exponent are not all zero. Digits beyond the exponent that are
/// all zero preserve the value exactly and are accepted under every mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rounding {
    /// Precision that would be lost is an error.
    Reject,
    /// A tie rounds away from zero.
    HalfUp,
    /// A tie rounds to the even minor unit.
    HalfEven,
    /// Truncate toward zero.
    Down,
}

/// A signed amount of minor units in one currency.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub struct Money {
    pub minor: i64,
    pub currency: Currency,
}

impl Money {
    pub fn new(minor: i64, currency: Currency) -> Money {
        Money { minor, currency }
    }

    /// Parses a decimal string such as `"19.99"` (spec 3.6).
    pub fn parse(s: &str, currency: Currency, rounding: Rounding) -> Result<Money, CoreError> {
        parse::parse(s, currency, rounding)
    }

    /// Parses a spec 3.1 wire object, e.g. `{"amount":"1999","currency":"USD"}`.
    /// Every violation is `HEPH-MONEY-422`.
    pub fn from_wire_json(json: &str) -> Result<Money, CoreError> {
        wire::from_wire_json(json)
    }

    /// Inverse of [`Money::from_wire_json`].
    pub fn to_wire_json(&self) -> String {
        wire::to_wire_json(self)
    }

    /// Formats with exactly `exponent` fractional digits and never `-0`.
    pub fn to_decimal_string(&self) -> String {
        let digits = self.minor.unsigned_abs().to_string();
        let exp = usize::from(self.currency.exponent);
        let sign = if self.minor < 0 { "-" } else { "" };
        if exp == 0 {
            return format!("{sign}{digits}");
        }
        let padded = format!("{digits:0>width$}", width = exp + 1);
        let (int, frac) = padded.split_at(padded.len() - exp);
        format!("{sign}{int}.{frac}")
    }

    pub fn checked_add(&self, other: &Money) -> Result<Money, CoreError> {
        self.same_currency(other)?;
        let minor = self
            .minor
            .checked_add(other.minor)
            .ok_or_else(|| invalid("addition overflows 64-bit minor units"))?;
        Ok(Money::new(minor, self.currency))
    }

    pub fn checked_sub(&self, other: &Money) -> Result<Money, CoreError> {
        self.same_currency(other)?;
        let minor = self
            .minor
            .checked_sub(other.minor)
            .ok_or_else(|| invalid("subtraction overflows 64-bit minor units"))?;
        Ok(Money::new(minor, self.currency))
    }

    pub fn checked_neg(&self) -> Result<Money, CoreError> {
        let minor = self
            .minor
            .checked_neg()
            .ok_or_else(|| invalid("negation overflows 64-bit minor units"))?;
        Ok(Money::new(minor, self.currency))
    }

    /// Splits by the largest-remainder method (spec 3.7).
    pub fn allocate(&self, ratios: &[u64]) -> Result<Vec<Money>, CoreError> {
        allocate::allocate(self, ratios)
    }

    fn same_currency(&self, other: &Money) -> Result<(), CoreError> {
        if self.currency == other.currency {
            return Ok(());
        }
        Err(CoreError::Money {
            code: MISMATCH,
            message: format!(
                "currency mismatch: {} and {}",
                self.currency.as_str(),
                other.currency.as_str()
            ),
        })
    }
}
