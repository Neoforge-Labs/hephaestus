# Contributing to Hephaestus

The standing rules for working in this repo — spec first, vectors from
independent sources, one home per capability, the Rust core's constraints,
maturity levels, the adopt-before-building table and the IP boundary — are in
[`CLAUDE.md`](CLAUDE.md), and they bind humans and agents alike. Read that
first; this file does not restate it.

What belongs here instead are the few procedures that **cannot be enforced by a
check** and so depend on a person doing them. Each one exists because an
automated gate was considered and found not to be able to close the hole.

## Changing a pinned external publication

Some normative data in this repo is transcribed from a standard published
elsewhere, and the publication is pinned by hash because its licence does not
let us vendor the file. Today that is the ISO 4217 currency registry:
`spec/currencies.yaml`, pinned by `spec/currencies.source.yaml` (see
[ADR 0017](docs/adr/0017-full-iso-4217-currency-table.md) and spec 3.3).

`tools/gen_currencies.py --verify-source <file>` proves that the registry is
exactly what a given file derives to and that the file matches the pinned
sha256. What it cannot prove is that the file came from the publisher: that is
attested by whoever changed the pin. The hash is therefore only as good as the
fetch behind it, and these rules are the mitigation.

**If you change `sha256` in a source pin:**

1. **Fetch it yourself, fresh, from the URL recorded in the pin.** Do not
   compute the hash from a file you already had, a colleague's copy, a mirror,
   an LLM's output or a package that bundles the data. If the recorded URL no
   longer serves it, update the URL in the same commit and say in the commit
   message where the new one came from.
2. **Re-transcribe; never hand-edit.** Run
   `uv run tools/gen_currencies.py --transcribe <file>`, then
   `--verify-source <file>`, then the generator with no arguments to regenerate
   the output it feeds. A single exponent edited by hand is a claim about the
   standard that nothing checks.
3. **Never change a pin in the same commit as a hand-edited value.** A commit
   that moves the pin *and* alters data under it is unreviewable: the new hash
   makes the new data verify, so the edit becomes invisible. Keep the pin move
   mechanical — pin plus `--transcribe` output, nothing else — and put any
   other change in its own commit.
4. **State the publication in the commit message:** the publisher's own
   version or publication date, the amendment or revision number if the
   publication carries one, the date you fetched it, and the new hash.

**If you are reviewing a change to a source pin**, the hash is the one thing
you must not take on trust:

1. **Fetch the file yourself** from the URL in the pin and confirm the sha256
   matches what the commit claims. This is the step the automation cannot do
   for you, and it is the whole reason this section exists.
2. **Run `--verify-source`** against your own copy, not the author's.
3. **Check the data diff is consistent with the publisher's own change notes.**
   A re-transcription that moves values the publisher did not announce means
   either the wrong file or the wrong URL.
4. **Reject a pin move bundled with anything else**, per rule 3 above.

A scheduled CI job (`.github/workflows/currency-source.yml`) re-derives the
registry from the pinned publication weekly, and the same job runs on any pull
request touching the registry, its pin or the generator. Neither run removes the
reviewer's duty above: both fetch over the network with no independent witness,
so they confirm the pin is self-consistent, not that it is honest.

## Conventions

Conventional Commits, branches `work/<topic>`, and no AI attribution in commit
messages, PR bodies or branch names. Run the checks for whatever you touched —
the list is under "Verify before you claim" in [`CLAUDE.md`](CLAUDE.md) — and
paste failures rather than summarising them away.
