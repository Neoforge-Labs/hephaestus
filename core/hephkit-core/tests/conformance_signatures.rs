mod common;

use base64::{engine::general_purpose::STANDARD, Engine};
use common::{assert_suites_covered, check, load};
use hephkit_core::{sign, verify, DEFAULT_TOLERANCE_SECS};

const WH: &str = "HEPH-WH-401";
const SECRET: &str = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw";

fn payload(input: &serde_json::Value) -> Vec<u8> {
    STANDARD
        .decode(input["payload_b64"].as_str().expect("payload_b64"))
        .expect("payload_b64 is base64")
}

#[test]
fn every_suite_file_is_exercised() {
    assert_suites_covered("signatures", &["sign", "verify"]);
}

#[test]
fn sign_vectors() {
    for c in load("signatures", "sign") {
        let i = &c.input;
        let got = sign(
            i["secret"].as_str().expect("secret"),
            i["msg_id"].as_str().expect("msg_id"),
            i["timestamp"].as_i64().expect("timestamp"),
            &payload(i),
        );
        check(&c.name, got, &c.expect, |e| {
            e["signature"].as_str().expect("signature").to_string()
        });
    }
}

#[test]
fn verify_vectors() {
    for c in load("signatures", "verify") {
        let i = &c.input;
        let h = |k: &str| {
            i["headers"][k]
                .as_str()
                .expect("header present")
                .to_string()
        };
        let got = verify(
            i["secret"].as_str().expect("secret"),
            &h("webhook-id"),
            &h("webhook-timestamp"),
            &h("webhook-signature"),
            &payload(i),
            i["now"].as_i64().expect("now"),
            DEFAULT_TOLERANCE_SECS,
        );
        check(&c.name, got, &c.expect, |e| {
            assert_eq!(e["ok"], true, "{}", c.name);
        });
    }
}

fn valid() -> (String, i64) {
    (sign(SECRET, "msg_1", 1000, b"body").unwrap(), 1000)
}

#[test]
fn equal_length_mismatch_rejected() {
    let (sig, ts) = valid();
    let b64 = sig.strip_prefix("v1,").unwrap();
    let mut raw = STANDARD.decode(b64).unwrap();
    raw[0] ^= 1;
    let flipped = format!("v1,{}", STANDARD.encode(&raw));
    assert_eq!(flipped.len(), sig.len());
    let err = verify(SECRET, "msg_1", &ts.to_string(), &flipped, b"body", ts, 300).unwrap_err();
    assert_eq!(err.code(), WH);
    verify(SECRET, "msg_1", &ts.to_string(), &sig, b"body", ts, 300).unwrap();
}

#[test]
fn hostile_timestamps_are_rejected_without_panic() {
    let (sig, _) = valid();
    for ts in [
        "999999999999999999999",
        "9223372036854775807",
        "9223372036854775808",
        "-1",
        "+1000",
        "1e3",
        "",
        " 1000",
        "1000 ",
        "1_000",
        "١٠٠٠",
    ] {
        for now in [1000, 0, i64::MAX, i64::MIN] {
            let r = verify(SECRET, "msg_1", ts, &sig, b"body", now, 300);
            assert_eq!(r.unwrap_err().code(), WH, "ts {ts:?} now {now}");
        }
    }
}

#[test]
fn extreme_clock_values_cannot_overflow() {
    // |now - timestamp| here is 2^64 - 1: it overflows i64 but not abs_diff.
    let max = i64::MAX.to_string();
    let sig = sign(SECRET, "m", i64::MAX, b"").unwrap();
    let far = verify(SECRET, "m", &max, &sig, b"", i64::MIN, i64::MAX);
    assert_eq!(far.unwrap_err().code(), WH);
    verify(SECRET, "m", &max, &sig, b"", i64::MAX, 300).unwrap();
}

#[test]
fn empty_and_negative_inputs_reject() {
    let (sig, ts) = valid();
    let t = ts.to_string();
    for (id, th, sh) in [
        ("", t.as_str(), sig.as_str()),
        ("msg_1", "", &sig),
        ("msg_1", &t, ""),
    ] {
        assert_eq!(
            verify(SECRET, id, th, sh, b"body", ts, 300)
                .unwrap_err()
                .code(),
            WH
        );
    }
    // Negative tolerance never accepts, even an exact clock match.
    assert_eq!(
        verify(SECRET, "msg_1", &t, &sig, b"body", ts, -1)
            .unwrap_err()
            .code(),
        WH
    );
    // Zero tolerance accepts only an exact match.
    verify(SECRET, "msg_1", &t, &sig, b"body", ts, 0).unwrap();
    assert!(verify(SECRET, "msg_1", &t, &sig, b"body", ts + 1, 0).is_err());
}

#[test]
fn bad_secrets_are_signature_errors() {
    for s in ["whsec_!!!notbase64", "", "whsec_", "not base64 at all"] {
        if s.is_empty() || s == "whsec_" {
            // An empty key is a valid (if useless) HMAC key; it must not panic.
            let _ = sign(s, "m", 1, b"x");
            continue;
        }
        assert_eq!(sign(s, "m", 1, b"x").unwrap_err().code(), WH);
        assert_eq!(
            verify(s, "m", "1", "v1,AAAA", b"x", 1, 300)
                .unwrap_err()
                .code(),
            WH
        );
    }
}

#[test]
fn header_grammar_edge_cases() {
    let (sig, ts) = valid();
    let t = ts.to_string();
    let ok = |h: &str| verify(SECRET, "msg_1", &t, h, b"body", ts, 300).is_ok();
    assert!(ok(&sig));
    assert!(ok(&format!("v2,AAAA {sig} v1,@@@")));
    assert!(ok(&format!("  {sig}  ")));
    assert!(!ok(&format!("V1,{}", sig.trim_start_matches("v1,"))));
    assert!(!ok(&format!("v1 {}", sig.trim_start_matches("v1,"))));
    assert!(!ok("v1,"));
    assert!(!ok(","));
    assert!(!ok("v1"));
}
