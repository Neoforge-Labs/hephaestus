mod common;

use common::{assert_suites_covered, check, load};
use hephkit_core::{canonical_json, content_hash_bytes, content_hash_json, new_uuid7};

const VAL: &str = "HEPH-VAL-422";

#[test]
fn every_suite_file_is_exercised() {
    assert_suites_covered("hashing", &["jcs", "content"]);
}

#[test]
fn jcs() {
    for c in load("hashing", "jcs") {
        let json = c.input["json"].as_str().expect("input.json is a string");
        check(&c.name, canonical_json(json), &c.expect, |e| {
            e["canonical"].as_str().expect("canonical").to_string()
        });
    }
}

#[test]
fn content() {
    for c in load("hashing", "content") {
        let json = c.input["json"].as_str().expect("input.json is a string");
        check(&c.name, content_hash_json(json), &c.expect, |e| {
            e["hash"].as_str().expect("hash").to_string()
        });
    }
}

#[test]
fn content_hash_bytes_is_prefixed_lowercase_hex() {
    // FIPS 180-2 appendix B.1 test vector for "abc".
    assert_eq!(
        content_hash_bytes(b"abc"),
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(
        content_hash_bytes(b""),
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
}

#[test]
fn hashing_errors_carry_the_validation_code() {
    for bad in ["", "{", "01", "[1,]", "{\"a\":1,}", "\"\u{1}\"", "\"\\x\""] {
        assert_eq!(canonical_json(bad).unwrap_err().code(), VAL, "{bad:?}");
        assert_eq!(content_hash_json(bad).unwrap_err().code(), VAL, "{bad:?}");
    }
}

#[test]
fn hazard_deep_nesting_is_an_error_not_an_abort() {
    for open_close in [("[", "]"), ("{\"a\":", "}")] {
        for depth in [100_000usize, 1_000_000] {
            let doc = format!(
                "{}1{}",
                open_close.0.repeat(depth),
                open_close.1.repeat(depth)
            );
            assert_eq!(canonical_json(&doc).unwrap_err().code(), VAL);
        }
    }
    // A document at a reasonable depth still works.
    // Spec 4.3: 128 levels are accepted, 129 are rejected.
    for (depth, accepted) in [(64usize, true), (128, true), (129, false)] {
        let doc = format!("{}1{}", "[".repeat(depth), "]".repeat(depth));
        match canonical_json(&doc) {
            Ok(out) => assert!(accepted && out == doc, "depth {depth}"),
            Err(e) => assert!(!accepted && e.code() == VAL, "depth {depth}"),
        }
    }
}

#[test]
fn hazard_large_inputs_stay_linear() {
    let long = format!("\"{}\"", "a\\n".repeat(2_000_000));
    assert_eq!(canonical_json(&long).unwrap().len(), long.len());
    let arr = format!("[{}0]", "0,".repeat(2_000_000));
    assert_eq!(canonical_json(&arr).unwrap(), arr);
    let obj = format!(
        "{{{}\"k\":0}}",
        (0..100_000)
            .map(|i| format!("\"{i}\":0,"))
            .collect::<String>()
    );
    assert!(canonical_json(&obj).is_ok());
}

#[test]
fn uuid7_is_version_7_and_time_ordered() {
    let mut ids: Vec<String> = (0..500).map(|_| new_uuid7()).collect();
    std::thread::sleep(std::time::Duration::from_millis(2));
    ids.extend((0..500).map(|_| new_uuid7()));
    assert_uuid7_shape_and_order(&ids);
}

#[test]
fn uuid7_is_monotonic_within_a_millisecond() {
    // No sleeps: 1,000 ids generated back to back share milliseconds.
    let ids: Vec<String> = (0..1_000).map(|_| new_uuid7()).collect();
    assert_uuid7_shape_and_order(&ids);
}

fn assert_uuid7_shape_and_order(ids: &[String]) {
    assert_eq!(ids.len(), 1_000);
    for id in ids {
        let b = id.as_bytes();
        assert_eq!(b.len(), 36, "{id}");
        for (i, ch) in id.char_indices() {
            if [8, 13, 18, 23].contains(&i) {
                assert_eq!(ch, '-', "{id}");
            } else {
                assert!(ch.is_ascii_digit() || ('a'..='f').contains(&ch), "{id}");
            }
        }
        assert_eq!(b[14], b'7', "version nibble: {id}");
        assert!(matches!(b[19], b'8' | b'9' | b'a' | b'b'), "variant: {id}");
    }
    let mut sorted = ids.to_vec();
    sorted.sort();
    assert_eq!(
        sorted, ids,
        "lexicographic order must equal generation order"
    );
    sorted.dedup();
    assert_eq!(sorted.len(), ids.len(), "ids must be unique");
}
