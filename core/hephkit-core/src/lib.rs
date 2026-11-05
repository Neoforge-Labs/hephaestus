//! Hephaestus correctness core. Maturity: experimental.
//!
//! No I/O, no global state, no panics on input: every fallible function
//! returns `Result<_, CoreError>`.

mod error;
mod hashing;
mod json;
mod money;
mod signatures;

pub use error::CoreError;
pub use hashing::{canonical_json, content_hash_bytes, content_hash_json, new_uuid7};
pub use money::{Currency, Money, Rounding};
pub use signatures::{sign, verify, DEFAULT_TOLERANCE_SECS};
