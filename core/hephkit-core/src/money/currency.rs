use super::currency_table::TABLE;
use super::invalid;
use crate::CoreError;

/// An ISO 4217 currency with a defined minor-unit exponent.
///
/// Deliberately derives no `PartialOrd`/`Ord`, and the absence is load-bearing
/// outside this file: it is the only reason `#[derive(PartialOrd)]` on [`Money`]
/// does not compile, and the compiler's error for that derive suggests adding
/// `Ord` here by name. An ordering on `Currency` would therefore unlock a
/// field-order ordering on `Money`, where `KES 100 < USD 50` must be
/// `HEPH-MONEY-409` and not a boolean (spec 3.8). If a `BTreeMap<Currency, _>`
/// or a sorted code list ever needs one, key it on the public `code` field
/// (`[u8; 3]`, which orders by ASCII) at the call site rather than ordering the
/// currency itself. `tests/money_no_infallible_ordering.rs` enforces this.
///
/// [`Money`]: super::Money
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub struct Currency {
    pub code: [u8; 3],
    pub exponent: u8,
}

impl Currency {
    /// Looks `code` up in the generated ISO 4217 table (spec 3.3); unknown or
    /// exponent-less codes are `HEPH-MONEY-422`.
    pub fn from_code(code: &str) -> Result<Currency, CoreError> {
        let key: [u8; 3] = match code.as_bytes().try_into() {
            Ok(key) => key,
            // Not three bytes, so not a code: no table lookup can match it.
            Err(_) => return Err(Self::unknown()),
        };
        match TABLE.binary_search_by(|(candidate, _)| candidate.cmp(&key)) {
            Ok(index) => {
                let (code, exponent) = TABLE[index];
                Ok(Currency { code, exponent })
            }
            Err(_) => Err(Self::unknown()),
        }
    }

    fn unknown() -> CoreError {
        invalid("unknown currency or currency without a minor-unit exponent")
    }

    pub(crate) fn as_str(&self) -> &str {
        // Table codes are ASCII; the fallback is unreachable but keeps this total.
        std::str::from_utf8(&self.code).unwrap_or("???")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `from_code` binary searches, so an unsorted or duplicated generated
    /// table would silently fail to find codes rather than fail loudly.
    #[test]
    fn generated_table_is_sorted_and_unique() {
        assert!(TABLE.windows(2).all(|pair| pair[0].0 < pair[1].0));
    }

    #[test]
    fn generated_table_holds_only_well_formed_entries() {
        for (code, exponent) in TABLE {
            assert!(
                code.iter().all(|b| b.is_ascii_uppercase()),
                "{code:?} is not three uppercase ASCII letters"
            );
            assert!(exponent <= 4, "{code:?} has exponent {exponent}");
        }
    }

    #[test]
    fn every_table_entry_round_trips_through_from_code() {
        for (code, exponent) in TABLE {
            let text = std::str::from_utf8(&code).expect("table codes are ASCII");
            let currency = Currency::from_code(text).expect(text);
            assert_eq!(currency.exponent, exponent, "{text}");
            assert_eq!(currency.as_str(), text);
        }
    }

    #[test]
    fn codes_of_the_wrong_length_are_rejected_without_a_lookup() {
        for code in ["", "US", "USDD", "\u{ff35}\u{ff33}\u{ff24}"] {
            assert!(Currency::from_code(code).is_err(), "{code:?}");
        }
    }
}
