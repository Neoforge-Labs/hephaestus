//! Differential check of the number path against Node's `JSON.stringify`
//! (ECMAScript `Number::toString`), the oracle RFC 8785 names.
//!
//! NOT part of the default `cargo test` run: it is `#[ignore]`d and needs
//! `node` on PATH. Run it after touching `write_double`, `shortest_digits` or
//! `even_tie` in `src/hashing.rs`:
//!
//! ```text
//! cargo test -p hephkit-core --release --test node_number_diff -- --ignored --nocapture
//! ```
//!
//! About 300,000 doubles; takes roughly 3 seconds in release (a few times that
//! in debug). The generator is seeded (`HEPH_DIFF_SEED`, default 1), so a
//! failure reproduces. Inputs are 21-significant-digit exponent literals, so
//! they are always float literals under spec 4.3.

use std::process::Command;

const GENERATOR: &str = r#"
let s = (Number(process.argv[1]) >>> 0) || 1;
const rnd = () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
const dv = new DataView(new ArrayBuffer(8));
const lits = [], want = [];
const add = (x) => { if (!isFinite(x)) return; lits.push(x.toExponential(20)); want.push(JSON.stringify(x)); };
// Random bit patterns: the whole double range, subnormals included.
for (let i = 0; i < 150000; i++) { dv.setUint32(0, rnd() * 2 ** 32 >>> 0); dv.setUint32(4, rnd() * 2 ** 32 >>> 0); add(dv.getFloat64(0)); }
// Exact midpoints (n + .25/.5/.75) where shortest-digit ties occur.
for (let i = 0; i < 100000; i++) { add(Math.floor(rnd() * 2 ** (44 + rnd() * 9)) + [0.25, 0.5, 0.75][i % 3]); }
// Large integers scaled by powers of ten, around the 1e21 and 1e-6 thresholds.
for (let i = 0; i < 50000; i++) { add(Math.floor(rnd() * 1e16) * Math.pow(10, Math.floor(rnd() * 40 - 20))); }
console.log(JSON.stringify({ lits: '[' + lits.join(',') + ']', want }));
"#;

#[test]
#[ignore = "needs node on PATH; run explicitly, see module docs"]
fn canonical_numbers_match_node_json_stringify() {
    let seed = std::env::var("HEPH_DIFF_SEED").unwrap_or_else(|_| "1".into());
    let out = Command::new("node")
        .args(["-e", GENERATOR, &seed])
        .output()
        .expect("node must be on PATH to run this ignored test");
    assert!(
        out.status.success(),
        "node failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("node output");
    let lits = payload["lits"].as_str().expect("lits");
    let want: Vec<&str> = payload["want"]
        .as_array()
        .expect("want")
        .iter()
        .map(|v| v.as_str().expect("want string"))
        .collect();

    let canonical = hephkit_core::canonical_json(lits).expect("all literals are valid floats");
    let got: Vec<&str> = canonical[1..canonical.len() - 1].split(',').collect();
    assert_eq!(got.len(), want.len());
    let mismatches: Vec<_> = got
        .iter()
        .zip(&want)
        .zip(lits[1..lits.len() - 1].split(','))
        .filter(|((g, w), _)| g != w)
        .take(10)
        .map(|((g, w), l)| format!("{l}: got {g}, node {w}"))
        .collect();
    assert!(mismatches.is_empty(), "mismatches: {mismatches:#?}");
    println!("compared {} doubles against node", got.len());
}
