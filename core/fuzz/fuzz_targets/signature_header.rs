#![no_main]

use hephkit_core::{verify, DEFAULT_TOLERANCE_SECS};
use libfuzzer_sys::fuzz_target;

const SECRET: &str = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw";

// Arbitrary headers must never panic. Layout: 8 bytes `now`, then the
// timestamp header and signature header separated by a NUL byte; the tail
// after a second NUL is the payload.
fuzz_target!(|data: &[u8]| {
    let Some((now_bytes, rest)) = data.split_at_checked(8) else {
        return;
    };
    let now = i64::from_le_bytes(now_bytes.try_into().unwrap_or([0; 8]));
    let mut parts = rest.splitn(3, |&b| b == 0);
    let ts = parts.next().unwrap_or_default();
    let sig = parts.next().unwrap_or_default();
    let payload = parts.next().unwrap_or_default();
    let (Ok(ts), Ok(sig)) = (std::str::from_utf8(ts), std::str::from_utf8(sig)) else {
        return;
    };
    let _ = verify(SECRET, "msg_fuzz", ts, sig, payload, now, DEFAULT_TOLERANCE_SECS);
    let _ = verify(sig, ts, ts, sig, payload, now, i64::MIN);
});
