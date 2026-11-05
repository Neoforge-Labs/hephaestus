use std::fmt;

/// Error returned by every fallible core function. `code` is a HEPH code from
/// `spec/errors.yaml`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CoreError {
    Money {
        code: &'static str,
        message: String,
    },
    Signature {
        code: &'static str,
        message: String,
    },
    /// Canonicalisation and hashing failures (`HEPH-VAL-422`).
    Hashing {
        code: &'static str,
        message: String,
    },
}

impl CoreError {
    /// The HEPH error code for this error.
    pub fn code(&self) -> &'static str {
        match self {
            CoreError::Money { code, .. }
            | CoreError::Signature { code, .. }
            | CoreError::Hashing { code, .. } => code,
        }
    }

    fn message(&self) -> &str {
        match self {
            CoreError::Money { message, .. }
            | CoreError::Signature { message, .. }
            | CoreError::Hashing { message, .. } => message,
        }
    }
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code(), self.message())
    }
}

impl std::error::Error for CoreError {}
