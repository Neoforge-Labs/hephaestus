//! Standard Webhooks signing and verification (spec section 5). Experimental.
//!
//! Every verification failure is `HEPH-WH-401` with the same message, so a caller (or an
//! attacker watching it) cannot tell which check failed (spec 5.6).

use crate::CoreError;
use base64::{engine::general_purpose::STANDARD, Engine};
use hmac::{Hmac, Mac};
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

/// Default timestamp tolerance in seconds, inclusive (spec 5.5).
pub const DEFAULT_TOLERANCE_SECS: i64 = 300;

const CODE: &str = "HEPH-WH-401";
const SECRET_PREFIX: &str = "whsec_";

fn reject() -> CoreError {
    CoreError::Signature {
        code: CODE,
        message: "webhook verification failed".to_string(),
    }
}

/// HMAC key from a secret: optional `whsec_` prefix stripped, the rest
/// base64-decoded (spec 5.2). `None` if it is not base64 or decodes to nothing:
/// an unset secret must never yield a working signature.
fn key_from_secret(secret: &str) -> Option<Vec<u8>> {
    let encoded = secret.strip_prefix(SECRET_PREFIX).unwrap_or(secret);
    STANDARD.decode(encoded).ok().filter(|key| !key.is_empty())
}

/// MAC over `{msg_id}.{timestamp}.{payload}`, payload as raw bytes.
fn mac_for(key: &[u8], msg_id: &str, timestamp: &str, payload: &[u8]) -> Option<HmacSha256> {
    let mut mac = HmacSha256::new_from_slice(key).ok()?;
    mac.update(msg_id.as_bytes());
    mac.update(b".");
    mac.update(timestamp.as_bytes());
    mac.update(b".");
    mac.update(payload);
    Some(mac)
}

/// Signs a message, returning `v1,<base64>` (spec 5.2). A secret that does not
/// decode to a non-empty key is a configuration error: `HEPH-VAL-422`.
pub fn sign(
    secret: &str,
    msg_id: &str,
    timestamp: i64,
    payload: &[u8],
) -> Result<String, CoreError> {
    let invalid_secret = || CoreError::Signature {
        code: "HEPH-VAL-422",
        message: "secret must be base64 that decodes to a non-empty key".to_string(),
    };
    let key = key_from_secret(secret).ok_or_else(invalid_secret)?;
    let mac = mac_for(&key, msg_id, &timestamp.to_string(), payload).ok_or_else(invalid_secret)?;
    Ok(format!(
        "v1,{}",
        STANDARD.encode(mac.finalize().into_bytes())
    ))
}

/// Parses the `webhook-timestamp` header: one or more ASCII digits and nothing
/// else (no sign, whitespace, exponent), fitting in `i64`.
fn parse_timestamp(header: &str) -> Option<i64> {
    if header.is_empty() || !header.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    header.parse().ok()
}

/// Decoded MACs of every well-formed `v1` entry in a `webhook-signature`
/// header. Entries are space separated; entries of any other version, or
/// without a comma, or with undecodable base64 are skipped (spec 5.3).
fn v1_signatures(header: &str) -> Vec<Vec<u8>> {
    header
        .split(' ')
        .filter_map(|entry| {
            let (version, encoded) = entry.split_once(',')?;
            if version != "v1" {
                return None;
            }
            STANDARD.decode(encoded).ok()
        })
        .collect()
}

/// Verifies a message. `now` is the verifier's clock in epoch seconds; the
/// timestamp must satisfy `|now - timestamp| <= tolerance_secs` (spec 5.5).
/// An absent header is the empty string and is rejected.
pub fn verify(
    secret: &str,
    msg_id: &str,
    timestamp_header: &str,
    signature_header: &str,
    payload: &[u8],
    now: i64,
    tolerance_secs: i64,
) -> Result<(), CoreError> {
    // Every check is evaluated, then combined, so the work done does not
    // depend on which one failed first.
    let timestamp = parse_timestamp(timestamp_header);
    let fresh = match (timestamp, u64::try_from(tolerance_secs)) {
        (Some(ts), Ok(tol)) => now.abs_diff(ts) <= tol,
        _ => false,
    };
    let mac =
        key_from_secret(secret).and_then(|key| mac_for(&key, msg_id, timestamp_header, payload));
    let mut matched = false;
    if let Some(mac) = &mac {
        for candidate in v1_signatures(signature_header) {
            // Constant-time comparison; no early exit on a match.
            matched |= mac.clone().verify_slice(&candidate).is_ok();
        }
    }
    if fresh && matched && !msg_id.is_empty() {
        Ok(())
    } else {
        Err(reject())
    }
}
