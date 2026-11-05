//! Guards spec 3.8: nothing in the money module may gain an infallible
//! ordering.
//!
//! `Money::checked_cmp` is fallible because two currencies have no ordering
//! (`HEPH-MONEY-409`), and `PartialOrd`/`Ord` cannot fail. A derived ordering
//! on `Money` compares field by field in declaration order, so
//! `KES 100 < USD 50` would return a confident boolean decided by nothing but
//! that order: a wrong answer on a money path, with no error.
//!
//! **Why this exists when the compiler already objects.** `#[derive(PartialOrd)]`
//! on `Money` does not compile today, because `Currency` derives no ordering
//! either (`error[E0277]: can't compare `Currency` with `Currency``). But that
//! error ends with `help: consider annotating `Currency` with `#[derive(Ord)]`,
//! so the compiler names the first step, and an `Ord` on `Currency` is
//! independently plausible: a `BTreeMap<Currency, _>` or a sorted code list
//! wants one, and nothing in `currency.rs` shows the money-path consequence.
//! Taking that suggestion alone compiles clean, and from there a derive on
//! `Money` compiles too. `Currency` is therefore the half of this guard that
//! matters; guarding only `Money` would guard the step the compiler catches and
//! miss the step it recommends.
//!
//! **What it reads.** Every `.rs` file under `src/money/`, at run time, so a new
//! file in the module is covered without anyone remembering to add it here. In
//! each it looks at two constructs, both reassembled across newlines first:
//!
//! - every `derive(...)` span, so a rustfmt-wrapped multi-line derive reads the
//!   same as a one-line one, a second stacked `#[derive(...)]` is seen, and the
//!   `derive(...)` inside a `#[cfg_attr(..., derive(PartialOrd))]` is seen too;
//! - every `impl ...` header, so a hand-written `impl PartialOrd for Money`
//!   cannot sidestep the derive check.
//!
//! `Ord` and `PartialOrd` are matched as whole identifiers, so `Ordering` — which
//! `checked_cmp` returns and `parse.rs` uses throughout — is not a match.
//!
//! Comments and string literals are removed before any of that, because the doc
//! comments on `Money` and `Currency` quote `#[derive(PartialOrd)]` while
//! explaining why it is absent. A guard that flagged them would be telling the
//! module off for documenting its own invariant, and rewording the comment to
//! dodge the tool would only move the problem to the next person who writes one.
//!
//! **Limits, so the next reader treats this as a tripwire and not a proof.** It
//! reads text, not a parse tree. It does not see an ordering reached through a
//! blanket impl in another crate, a macro that expands to one, an `Ord` bound
//! satisfied outside `src/money/`, an alias import such as
//! `use std::cmp::PartialOrd as P`, or an ordering added to a type the money
//! types merely contain. The second test in this file guards against the guard
//! going vacuous, which is the failure mode that would otherwise hide all of
//! the above.
//!
//! One limit is not merely missed but *blinding*, so it is refused outright
//! rather than documented. The stripper handles line comments, nested block
//! comments, escaped strings and raw strings, but a `'"'` char literal would
//! open a phantom string: everything after it **in that file** is discarded, so
//! every derive and impl below it becomes invisible and the scan passes in
//! silence — the one outcome a guard must never produce. Since a new ordering
//! impl would most likely be appended at the end of a file, below any helper
//! that introduced the literal, this is the live shape of the risk rather than
//! a theoretical one. [`money_sources`] therefore refuses to run if any source
//! holds such a literal, so the blindness surfaces as a stop with instructions.
//! None exists today; the plausible route in is a JSON-escape helper needing
//! `c == '"'`.

use std::path::{Path, PathBuf};

/// The traits this module must never acquire. `Ord` also appears inside
/// `PartialOrd`, but both are listed so a failure names the one it found.
const FORBIDDEN: [&str; 2] = ["PartialOrd", "Ord"];

/// One scanned file: its path relative to the crate, its text as written, and
/// that text with comments and string literals removed by [`code_only`].
struct Source {
    file: String,
    raw: String,
    code: String,
}

/// A char literal holding a double quote defeats [`code_only`] silently, so
/// finding one is a hard stop rather than a documented limit. Both spellings
/// are listed; `b'"'` contains the first.
const BLINDING: [&str; 2] = ["'\"'", "'\\\"'"];

/// Every `.rs` file under `src/money/`. Recurses, so a future submodule
/// directory is covered, and refuses to return anything at all if a source
/// holds a sequence that would blind the scan.
fn money_sources() -> Vec<Source> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut found = Vec::new();
    collect(&root.join("src/money"), &root, &mut found);
    assert!(
        !found.is_empty(),
        "no .rs files found under src/money: this guard is reading the wrong place"
    );
    found.sort_by(|a, b| a.file.cmp(&b.file));
    for source in &found {
        if let Some(sequence) = blinding_sequence(&source.raw) {
            panic!(
                "{}: holds the char literal {sequence}, which this guard cannot read past.\n\n\
                 `code_only` treats the double quote as the start of a string literal, so \
                 everything after it in this file is discarded: every derive and impl below it \
                 goes unseen and the scan passes in silence, while the module may derive an \
                 ordering. Stopping here instead, because a guard that goes quiet is worse than \
                 no guard.\n\
                 To fix: teach `code_only` to consume char literals (after `'`, a `\\` escape or \
                 a single character followed by `'` is a literal; anything else is a lifetime), \
                 then drop this check. Do not work around it by rewriting the source.",
                source.file
            );
        }
    }
    found
}

/// The first sequence in `source` that would blind [`code_only`], if any.
fn blinding_sequence(source: &str) -> Option<&'static str> {
    BLINDING.into_iter().find(|s| source.contains(s))
}

fn collect(dir: &Path, root: &Path, out: &mut Vec<Source>) {
    let entries =
        std::fs::read_dir(dir).unwrap_or_else(|e| panic!("cannot read {}: {e}", dir.display()));
    for entry in entries {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            collect(&path, root, out);
        } else if path.extension().is_some_and(|e| e == "rs") {
            let text = std::fs::read_to_string(&path)
                .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
            let label = path
                .strip_prefix(root)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/");
            out.push(Source {
                file: label,
                code: code_only(&text),
                raw: text,
            });
        }
    }
}

/// `source` with comments and string-literal contents removed, newlines kept so
/// line structure survives for [`impl_headers`]. Handles `//`, nested `/* */`,
/// escaped `"..."` and raw `r#"..."#`/`br"..."`, which is what the money sources
/// contain; a `'"'` char literal would confuse it and none exists here.
fn code_only(source: &str) -> String {
    let b = source.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(b.len());
    let mut i = 0;
    let is_word = |c: u8| c.is_ascii_alphanumeric() || c == b'_';
    while i < b.len() {
        // Line comment: drop it, keep the newline.
        if b[i] == b'/' && b.get(i + 1) == Some(&b'/') {
            while i < b.len() && b[i] != b'\n' {
                i += 1;
            }
            continue;
        }
        // Block comment, nestable in Rust. Keep its newlines.
        if b[i] == b'/' && b.get(i + 1) == Some(&b'*') {
            let mut depth = 1usize;
            i += 2;
            while i < b.len() && depth > 0 {
                if b[i] == b'/' && b.get(i + 1) == Some(&b'*') {
                    depth += 1;
                    i += 2;
                } else if b[i] == b'*' && b.get(i + 1) == Some(&b'/') {
                    depth -= 1;
                    i += 2;
                } else {
                    if b[i] == b'\n' {
                        out.push(b'\n');
                    }
                    i += 1;
                }
            }
            continue;
        }
        // Raw string: an `r`, optionally preceded by `b`, then `#`*, then `"`.
        // Only at an identifier boundary, so `expr` is never mistaken for one.
        let raw_start = (b[i] == b'r' || (b[i] == b'b' && b.get(i + 1) == Some(&b'r')))
            && i.checked_sub(1).is_none_or(|p| !is_word(b[p]));
        if raw_start {
            let mut j = if b[i] == b'b' { i + 2 } else { i + 1 };
            let hash_start = j;
            while b.get(j) == Some(&b'#') {
                j += 1;
            }
            if b.get(j) == Some(&b'"') {
                let hashes = j - hash_start;
                let close = format!("\"{}", "#".repeat(hashes));
                out.extend_from_slice(b"\"\"");
                j += 1;
                match source[j..].find(&close) {
                    Some(offset) => i = j + offset + close.len(),
                    None => i = b.len(),
                }
                continue;
            }
        }
        // Plain string, with backslash escapes.
        if b[i] == b'"' {
            out.extend_from_slice(b"\"\"");
            i += 1;
            while i < b.len() && b[i] != b'"' {
                if b[i] == b'\\' {
                    i += 1;
                }
                i += 1;
            }
            i += 1;
            continue;
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8(out).expect("stripping whole comments and literals keeps UTF-8 intact")
}

/// Collapses runs of whitespace, so a construct spread over several lines
/// compares equal to the same construct written on one.
fn flatten(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Every `derive(...)` span in `source`, flattened. Reads forward to the
/// matching parenthesis rather than to the end of the line, which is what makes
/// a wrapped derive visible; an unclosed `derive(` is skipped rather than
/// swallowing the rest of the file.
fn derive_spans(source: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut at = 0;
    while let Some(offset) = source[at..].find("derive(") {
        let start = at + offset;
        let open = start + "derive".len();
        let mut depth = 0usize;
        let mut end = None;
        for (i, ch) in source[open..].char_indices() {
            match ch {
                '(' => depth += 1,
                ')' => {
                    depth -= 1;
                    if depth == 0 {
                        end = Some(open + i + 1);
                        break;
                    }
                }
                _ => {}
            }
        }
        match end {
            Some(e) => {
                out.push(flatten(&source[start..e]));
                at = e;
            }
            None => at = open,
        }
    }
    out
}

/// Every `impl ...` header in `source` (up to the opening brace), flattened.
/// Joins continuation lines, so a wrapped `impl` header is still one header.
/// Lines inside comments are skipped, so prose using the word is not a header.
fn impl_headers(source: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut lines = source.lines();
    while let Some(line) = lines.next() {
        let trimmed = line.trim();
        let starts_impl = trimmed == "impl"
            || trimmed.starts_with("impl ")
            || trimmed.starts_with("impl<")
            || trimmed.starts_with("unsafe impl");
        if trimmed.starts_with("//") || !starts_impl {
            continue;
        }
        let mut header = trimmed.to_string();
        while !header.contains('{') && !header.ends_with(';') {
            match lines.next() {
                Some(next) => {
                    header.push(' ');
                    header.push_str(next.trim());
                }
                None => break,
            }
        }
        let end = header.find('{').unwrap_or(header.len());
        out.push(flatten(&header[..end]));
    }
    out
}

/// True when `needle` occurs in `haystack` as a whole Rust identifier, so
/// `Ordering` does not count as `Ord`.
fn has_identifier(haystack: &str, needle: &str) -> bool {
    let is_word = |c: char| c.is_alphanumeric() || c == '_';
    let mut at = 0;
    while let Some(offset) = haystack[at..].find(needle) {
        let start = at + offset;
        let end = start + needle.len();
        let before_free = haystack[..start].chars().next_back().is_none_or(|c| !is_word(c));
        let after_free = haystack[end..].chars().next().is_none_or(|c| !is_word(c));
        if before_free && after_free {
            return true;
        }
        at = end;
    }
    false
}

#[test]
fn the_money_module_derives_and_implements_no_ordering() {
    for source in money_sources() {
        let file = &source.file;
        let constructs = derive_spans(&source.code)
            .into_iter()
            .map(|d| ("derive", d))
            .chain(impl_headers(&source.code).into_iter().map(|i| ("impl", i)));
        for (kind, text) in constructs {
            for trait_name in FORBIDDEN {
                assert!(
                    !has_identifier(&text, trait_name),
                    "{file}: this {kind} brings {trait_name} into the money module:\n  \
                     {text}\n\n\
                     spec 3.8: ordering two amounts can fail (HEPH-MONEY-409) and \
                     PartialOrd/Ord cannot. A derived ordering compares field by field in \
                     declaration order, so `KES 100 < USD 50` would answer with a boolean \
                     decided by field order. Use `Money::checked_cmp`, which returns \
                     `Result<Ordering, CoreError>`.\n\
                     Currency is guarded by the same rule: an ordering on Currency is what \
                     makes a derive on Money compile, and the compiler suggests it by name. \
                     To sort currencies, key on the public `code` field at the call site."
                );
            }
        }
    }
}

/// The failure mode that would hide every other one: the guard still reading,
/// still finding the two structs and their derives, and still able to tell an
/// ordering from an `Ordering`. Without this, renaming a file or wrapping a
/// derive could turn the test above green by making it look at nothing.
#[test]
fn the_guard_still_sees_what_it_claims_to_see() {
    let sources = money_sources();
    let names: Vec<&str> = sources.iter().map(|s| s.file.as_str()).collect();
    for required in ["src/money/mod.rs", "src/money/currency.rs"] {
        assert!(
            names.contains(&required),
            "{required} is not among the files scanned ({names:?})"
        );
    }

    // Each guarded struct is still declared, and still carries a derive for the
    // scan above to inspect.
    for (file, struct_name) in [
        ("src/money/mod.rs", "Money"),
        ("src/money/currency.rs", "Currency"),
    ] {
        let source = sources
            .iter()
            .find(|s| s.file == file)
            .unwrap_or_else(|| panic!("{file} not scanned"));
        assert!(
            source.code.contains(&format!("pub struct {struct_name}")),
            "{file}: no `pub struct {struct_name}`; this guard has lost its target"
        );
        assert!(
            !derive_spans(&source.code).is_empty(),
            "{file}: no `derive(...)` found; this guard would pass vacuously"
        );
    }

    // The matcher distinguishes the trait from the enum `checked_cmp` returns.
    assert!(!has_identifier("use std::cmp::Ordering;", "Ord"));
    assert!(!has_identifier("Result<Ordering, CoreError>", "Ord"));
    assert!(has_identifier("#[derive(Eq, Ord)]", "Ord"));

    // The stripper: prose about the invariant is not a violation of it, and a
    // literal cannot hide code or swallow it.
    assert!(
        derive_spans(&code_only("/// why `#[derive(PartialOrd)]` is absent")).is_empty(),
        "a derive quoted in a doc comment must not count as a derive"
    );
    assert!(
        derive_spans(&code_only("/* #[derive(Ord)] */\n#[derive(Eq)]\npub struct X;"))
            == vec!["derive(Eq)"],
        "a block comment must be dropped and the real derive kept"
    );
    assert!(
        has_identifier(
            &code_only("let s = \"// not a comment\";\n#[derive(Ord)]\npub struct X;"),
            "Ord"
        ),
        "a `//` inside a string must not comment out the code after it"
    );
    assert!(
        derive_spans(&code_only("let s = r#\"derive(Ord)\"#;")).is_empty(),
        "a raw string must not contribute a derive"
    );

    // The blinding sequence, recorded rather than described: a `'"'` char
    // literal really does make the scan see nothing, and the check really does
    // catch it. These two assertions are why `money_sources` refuses to run on
    // a source holding one.
    let blinded = "let q = '\"';\n#[derive(Ord)]\npub struct X;";
    assert!(
        derive_spans(&code_only(blinded)).is_empty(),
        "the premise of the blinding check has changed: code_only now reads past a '\\\"' char \
         literal, so the hard stop in money_sources is obsolete and should be replaced by \
         proper char-literal handling"
    );
    assert_eq!(blinding_sequence(blinded), Some("'\"'"));
    assert_eq!(blinding_sequence("let q = '\\\"';"), Some("'\\\"'"));
    assert_eq!(blinding_sequence("let c = 'a'; let l: &'static str = \"x\";"), None);
    // The real sources are clean, which is what lets the scan above mean anything.
    for source in &sources {
        assert_eq!(blinding_sequence(&source.raw), None, "{}", source.file);
    }
    // The real sources still carry their code after stripping.
    let wire = sources
        .iter()
        .find(|s| s.file == "src/money/wire.rs")
        .expect("wire.rs is scanned; it holds the raw strings the stripper must survive");
    assert!(
        wire.code.contains("pub(super) fn to_wire_json"),
        "stripping literals in wire.rs must not have eaten its code"
    );

    // The shapes this guard was hardened for: a rustfmt-wrapped derive, a
    // stacked second derive, a cfg_attr derive and a wrapped impl header. Each
    // must come back visible and carrying the forbidden name.
    let wrapped = "#[derive(\n    Debug,\n    Clone,\n    PartialOrd,\n    Ord,\n)]\npub struct X;";
    assert_eq!(
        derive_spans(wrapped),
        vec!["derive( Debug, Clone, PartialOrd, Ord, )"],
        "a wrapped derive must be reassembled, or the guard goes quiet when rustfmt wraps it"
    );
    let stacked = "#[derive(Debug)]\n#[derive(Ord)]\npub struct X;";
    assert_eq!(derive_spans(stacked).len(), 2, "a stacked derive must be seen");
    let gated = "#[cfg_attr(feature = \"x\", derive(PartialOrd))]\npub struct X;";
    assert!(has_identifier(&derive_spans(gated)[0], "PartialOrd"));
    let impl_wrapped = "impl PartialOrd\n    for Money\n{\n    fn partial_cmp() {}\n}";
    assert_eq!(impl_headers(impl_wrapped), vec!["impl PartialOrd for Money"]);
}
