//! Hephaestus correctness core. Experimental.
//!
//! No I/O, no global state, no panics on input: every fallible function
//! returns `Result<_, CoreError>`.

mod error;
mod money;

pub use error::CoreError;
pub use money::{Currency, Money, Rounding};
