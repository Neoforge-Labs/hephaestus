//! Guards spec 3.8: neither `Money` nor `Currency` may gain an infallible
//! ordering.
//!
//! `Money::checked_cmp` is fallible because two currencies have no ordering
//! (`HEPH-MONEY-409`), and `PartialOrd`/`Ord` cannot fail. A derived ordering
//! on `Money` compares field by field in declaration order, so
//! `KES 100 < USD 50` would return a confident boolean decided by nothing but
//! that order: a wrong answer on a money path, with no error.
//!
//! The type system already blocks the single-edit version — `Currency` derives
//! no `PartialOrd`, so `#[derive(PartialOrd)]` on `Money` does not compile
//! (`error[E0277]: can't compare `Currency` with `Currency``). This test
//! exists because that error ends with `help: consider annotating `Currency`
//! with `#[derive(Ord)]`, so the compiler names the first step, and an `Ord`
//! on `Currency` is independently plausible: a `BTreeMap<Currency, _>` or a
//! sorted code list wants one, and nothing in `currency.rs` shows the
//! money-path consequence. Once that landed the compiler would fall silent and
//! only a doc comment would stand between the next edit and the wrong answer.
//!
//! `Currency` is therefore the half of this test that matters. Guarding only
//! `Money` would guard the step the compiler already catches and leave the
//! step it recommends.

/// Read at compile time, so the guard travels with `cargo test -p
/// hephkit-core` and cannot drift from the sources it describes.
const MONEY: &str = include_str!("../src/money/mod.rs");
const CURRENCY: &str = include_str!("../src/money/currency.rs");

/// The `#[derive(...)]` line attached to `pub struct <name>`: the nearest one
/// above the declaration. Panics rather than passing vacuously if the
/// declaration or its derive moves, because a guard that silently stops
/// looking at anything is worse than no guard.
fn derive_of(source: &str, name: &str) -> String {
    let lines: Vec<&str> = source.lines().collect();
    let declared_at = lines
        .iter()
        .position(|l| l.trim_start().starts_with(&format!("pub struct {name}")))
        .unwrap_or_else(|| panic!("no `pub struct {name}` in the source"));
    lines[..declared_at]
        .iter()
        .rev()
        .find(|l| l.trim_start().starts_with("#[derive("))
        .unwrap_or_else(|| panic!("`pub struct {name}` has no `#[derive(...)]` above it"))
        .trim()
        .to_string()
}

#[test]
fn money_and_currency_derive_no_ordering() {
    for (name, source) in [("Money", MONEY), ("Currency", CURRENCY)] {
        let derive = derive_of(source, name);
        // `Ord` as a substring catches `PartialOrd` too, which is the one that
        // supplies the comparison operators.
        assert!(
            !derive.contains("Ord"),
            "{name} derives an ordering: {derive}\n\
             spec 3.8: ordering two amounts can fail (HEPH-MONEY-409) and PartialOrd/Ord \
             cannot. A derived ordering compares field by field in declaration order, so \
             `KES 100 < USD 50` would answer with a boolean decided by field order. Use \
             `Money::checked_cmp`, which returns `Result<Ordering, CoreError>`.\n\
             Currency is guarded for the same rule: an ordering on Currency is what makes \
             a derive on Money compile, and the compiler suggests it by name."
        );
    }
}
