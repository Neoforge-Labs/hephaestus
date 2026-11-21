# Execution ledger — hephkit.lab Wave 2

The record of executing [the Wave 2 plan](2026-11-21-hephkit-lab-wave-2-proof.md): what was
decided where the plan was wrong, silent or contradicted by `CLAUDE.md` or the spec, and what
each of those decisions costs if it turns out to be wrong. It is kept because the plan's text
no longer describes what was built in fifty-eight places, and the merge's own history records
the change without the argument behind it.

Read the numbered rulings as the substantive part. Everything else — the pre-flight scan, the
per-task completion lines, the deferred-minor lists — is the trail that produced them.

The rulings are numbered in the order they were made, and the numbering is the sequence to
follow: this was written as an append-as-you-go ledger against a fixed anchor, so a handful of
entries (Rulings 14 and 32, and each "Task N dispatched" line) sit out of order on the page.
Ruling 38 was withdrawn on its premise and says so where it stands.

Spec (binding authority): docs/superpowers/specs/2026-11-12-hephkit-lab-research-core-design.md
Branch: work/lab-wave-2-proof, based on origin/main eae2e1e, merged to main as 235ef80
Plan committed as b21da4e (first commit on the branch); branch tip f451c84, 34 commits.

Verified at the merge: 722 passed (1 skipped, PyTorch absent) at 99.69% coverage on
`hephkit.lab`, `mypy --strict` clean over 16 files, `check_vectors`/`check_adrs`/
`check_modules`/`check_registry` silent, `tools/tests` 407 passed, and
`examples/lab-replay/gate_test.sh` PASS.

Tasks 7-10 and 14 of the plan did not run: adopting CausalPhylo is blocked on its
relicensing, and the only release on PyPI is non-commercial (Ruling 5).

## Pre-flight scan

Pairs of tasks that share a file or an interface:

| Tasks | Produced → consumed | Found |
| --- | --- | --- |
| 1 → 2, 3 | spec §10 normative text → §10.2 digest composition, §10.3 resolution | agree |
| 1 → 2, 11, 12 | schema `suite` enum + `MIN_CASES` entries → the three vector files | check_vectors red from Task 1 to Task 12 — Ruling 1 |
| 2 → 4 | `Manifest`, `data_hash`, `require` → `read_frame`, `query` | agree |
| 2 → 5 | `Manifest`, `require` → `push`, `pull`, `data_card` | agree |
| 2 → 8, 9, 10 | `require` → the causal modules | blocked set, Ruling 5 |
| 2, 6, 8, 11 | `spec/modules.yaml`, one row each | sequential, no collision |
| 2, 11, 12 | `tests/test_conformance.py`, one runner each | sequential, no collision |
| 4 → 7 | `tests/test_extras.py` created then modified | Ruling 3 moves creation to Task 2 |
| 11 → 12 → 13 | `stats.py` grown over three tasks | agree — disjoint signatures, no redefinition |
| 13 | `require("scipy", extra="stats")` → `stats = ["scipy>=1.14"]` in pyproject | agree, extra already exists |
| 9, 10 → 7 | `pl.DataFrame` annotations → `hephkit-lab[data]` inside `[causal]` (plan line 466) | agree, blocked set |
| 14 → 1–13 | the whole wave | blocked set, Ruling 5 |
| 4 vs File Structure table | `.github/workflows/python-ci.yml` vs `ci.yml` | no conflict, Ruling 4 |

Each task against itself (tests vs code vs files):

| Task | Found |
| --- | --- |
| 1 | Step 4 expects `check_vectors.py` to fail; that is deliberate — Ruling 1 |
| 2 | creates `extras.py` but names no test module for it — Ruling 3 |
| 3 | agrees |
| 4 | agrees |
| 5 | agrees (`cards.py` + `test_data_cards.py` both listed) |
| 6 | agrees |
| 7–10 | blocked before self-agreement matters — Ruling 5 |
| 11 | agrees; no scipy in effect sizes, consistent with Task 13 owning it |
| 12 | agrees; the decision table in the task text is what the vectors pin |
| 13 | agrees; contract-tested, not vectored, per design §9.3 |
| 14 | blocked — Ruling 5 |
| 15 | four docs pages, one per module; only three modules will exist — Ruling 5 |

Verified against the repository, not assumed: `tools/check_modules.py` resolves a dotted
row `lab.data` to `lab/data/__init__.py` and scans directories as modules, so `lab.data`
as a package is valid; `spec/errors.yaml` carries exactly four LAB codes (422, 409, 424,
412); `python/hephkit-lab/pyproject.toml` already declares the `data`, `causal` and
`stats` extras; `.github/workflows/python-ci.yml` is what runs `hephkit-lab:test-fast`.

## Rulings

Ruling 1: Task 1 leaves `python tools/check_vectors.py` reporting three missing suite
files (`lab/manifest.json`, `lab/effects.json`, `lab/selection.json`), and that stays red
until Task 12 lands the last of them — the plan's Task 1 Step 4 says so. Every dispatch
from Task 1 through Task 12 carries that fact, and no implementer may clear it by removing
a `suite` enum entry or lowering a `MIN_CASES` number. Why: the enum and the minimums are
the gate the vectors are written against; stamping them first is what makes a missing
vector file a failure rather than a silence. Cost if wrong: an implementer reads a correct
red checker as a regression and weakens the gate to make it green.

Ruling 2: `ManifestError` carries `HEPH-LAB-412`, not the plan's `HEPH-LAB-422`, and the
§10.4 refusal cases in `conformance/lab/manifest.json` expect `{"error":
"HEPH-LAB-412"}`. Why: `spec/errors.yaml` is the binding registry, 422 is titled
"Experiment config failed validation", and the registry routes manifest failures away from
it twice — 422's own guidance ("Input data that fails a manifest or a gate is
HEPH-LAB-412") and 424's ("If the artefact exists but says the wrong thing, the code is
HEPH-LAB-412"). `StatsError` keeps `HEPH-LAB-422`: a `TestRequest`, or a sample handed to
an effect size, is the configuration of that statistic, and the registry's exclusion is
specifically about manifests and gates, neither of which `lab.stats` touches. Cost if
wrong: one constant and roughly five vector cases change.

Ruling 3: Task 2 creates `python/hephkit-lab/tests/test_extras.py` along with
`extras.py`, and Task 4 extends that file rather than creating it. Why: the
`--cov-fail-under=90` gate runs at Task 2's own commit, and `extras.py` shipped with no
test module would either fail it or be carried by incidental coverage. Cost if wrong: one
test file is created a task earlier than the plan's File Structure table says.

Ruling 4: Task 4's `.github/workflows/python-ci.yml` is the right file — it is the
workflow that runs `moon run hephkit-lab:test-fast hephkit-lab:typecheck`. The File
Structure table's `.github/workflows/ci.yml` row belongs to Task 14's gate job. Both files
exist; the plan is not in conflict with itself. Cost if wrong: nothing — the two edits are
in different files for different reasons.

Ruling 5: Tasks 7, 8, 9, 10 and 14 do not start. Verified against PyPI at execution time:
`causalphylo` has exactly one release, 0.1.0, carrying
`LicenseRef-CausalPhylo-NonCommercial`, so the MIT precondition the user set has not
landed. Execution order is 1, 2, 3, 4, 5, 6, 11, 12, 13, then Task 15 restricted to the
three modules that will exist (`lab.data`, `lab.sources`, `lab.stats`); the `lab.causal`
docs page and the causal arm of the import probe are parked with the blocked set. Why: the
plan's own precondition says to stop and raise it rather than pin the non-commercial
version or vendor the algorithm, and the rest of the wave does not depend on it. Cost if
wrong: the causal half of the wave becomes a second branch once the MIT release exists.

Ruling 6: no AI attribution in any commit on this branch. Why: CLAUDE.md says "No AI
attribution in commits, PR bodies or branch names", and the harness's own attribution
reminder defers to a project rule. The plan commit was written with a `Co-Authored-By`
trailer and amended to drop it (b21da4e → d898575); every implementer dispatch carries
the rule. Cost if wrong: a trailer has to be stripped from the branch's history.

## Task log

Task 1 dispatched (sonnet), BASE d898575. Reported DONE_WITH_CONCERNS at 1e39b99.

Ruling 7: bare `python` is not on PATH in this environment, so the plan's checker commands
(`python tools/check_adrs.py` and friends) do not run as written. Every implementer dispatch
from here on says to run them through `uv run --with pyyaml --with jsonschema python
tools/<checker>.py`, or through the project's moon tasks. Why: the checkers declare their
dependencies inline (PEP 723) and uv is the repo's only assumed tool. Cost if wrong: an
implementer reports a checker as broken when it was never invoked.

Task 1 concerns adjudicated before review:
- Three changes beyond the brief (the spec intro's part count naming §10, the
  `tools/tests/test_check_vectors.py` fixture's `spec` field, the regenerated
  `docs/site/content/spec/index.md`) are correct consequences of writing §10 and of the
  schema const; kept.
- Two of the three new `MIN_CASES` comments described the wrong suites — `lab.effects`'s
  invented an "effect document" that does not exist, and `lab.selection`'s described spec
  §10.3's date-to-release resolution instead of statistical test selection. Implementer
  resumed with the exact replacement text before review, since a comment on a gate is what
  the next author reads to know what the suite owes.

Task 1 review (sonnet, d898575..e25bde0): spec ❌ — one Important, four Minor.

Ruling 8 (Important 1, the file-entry unknown-member rule): **keep it and ratify it.** The
reviewer is right that `spec/heph-spec.md` §10.1's "Each entry of `files` MUST carry every
member of this table, and MUST NOT carry a member this section does not define" goes beyond
the brief's four bullets. But the plan specifies `class FileDigest(BaseModel)` as frozen with
`extra="forbid"`, so Task 2's code will refuse an unknown member on a file entry whatever the
spec says, and a spec looser than the code it governs is the failure this repository is built
to prevent. §10.4 therefore gains the matching refusal so the `lab.manifest` vectors can pin
it, rather than the sentence being deleted. Cost if wrong: one spec sentence, one refusal
bullet and one vector case come back out.

Ruling 9 (Minor 2, plan-mandated): `published`'s format is stated. §10.3 compares `published`
to a date *d* with "less than or equal to", which is only defined once both sides share a
format; the plan's own §10.3 bullet left it out. §10.1's `captured_at` is already pinned as an
RFC 3339 `full-date`, so `published` is too. Why now and not in Task 3: otherwise Task 3
invents the answer in code and the spec never says it. Cost if wrong: one clause.

Ruling 10 (Minor 4, plan-mandated): `bytes` is a **non-negative** integer in §10.1's table.
A negative `bytes` is already unreachable through the §10.4 refusal that compares it to the
file it names, but Task 2's `FileDigest` needs the constraint stated somewhere normative
rather than guessed. Cost if wrong: one word.

Ruling 11 (Minor 1): §10 is reshaped into the paragraph-numbered clause form §7–§9 use,
dropping the `### 10.1` headings. The `###` shape came from my own dispatch, not from the
plan, and no other section of the spec uses it. Fixed now, one task in, rather than after
fourteen more tasks and three vector suites cite §10 — the change is presentational and moves
no requirement. Cost if wrong: a 40-line reformat to undo.

Task 1: minor (deferred): none — Minors 1-4 were all ruled on and folded into fix round 1.

Task 1: fix round 1/5 dispatched (5 findings: the file-entry rule ratified in §10.4,
`published`'s format, `bytes` non-negative, the §10 reshape to paragraph clauses, the
decisions bullet's wording); commits e25bde0..e4120cf, amended.

Task 1: fix round 1/5 re-review: all 5 addressed, no new breakage.
Task 1: complete (commits d898575..e4120cf, review clean). Spec is 0.6.0; §10 has four
paragraph clauses and five refusals in §10.4; the three suites are in the schema enum and
`MIN_CASES`; `check_vectors` is red on exactly the three missing suite files.

Ruling 12: from Task 2 on, a fix round adds a **new commit** instead of amending. Why: the
amend here left `e4120cf` not a descendant of `e25bde0`, so `scripts/review-package`
refused the range and the fix diff had to be assembled by hand. Cost if wrong: a few extra
commits on the branch, which `finishing-a-development-branch` can squash.

Task 2 dispatched (sonnet), BASE e4120cf. Dispatch carries Rulings 1, 2, 3, 7 and the fact
that §10.4 now has five refusals, plus explicit instructions for deriving the vectors from
`rfc8785` + `hashlib` rather than from our own code (CLAUDE.md rule 2). Reported
DONE_WITH_CONCERNS at 4e0d67b: 450 passed, coverage 99.84%, mypy clean, `check_vectors`
down to the two expected missing files.

Checked myself rather than taking the report's word: the implementer's concern 5
(`tools/tests/test_gen_idempotency_vectors.py::test_committed_vectors_are_current` failing
with a ModuleNotFoundError) is an incomplete ad-hoc `uv --with` environment, not a
regression from Task 1's `SPEC_VERSION` re-stamp. Run with pytest, pyyaml, jsonschema,
rfc8785, standardwebhooks and cryptography present, `tools/tests/test_gen_idempotency_vectors.py`
is 11 passed. No action.

Ruling 13 (spec defect found by Task 2, load-bearing): **spec §10.4 gains a sixth refusal
— a `files` entry whose `sha256` disagrees with the bytes of the file it names.** The
implementer built `verify_manifest` to check `bytes` and file presence but deliberately not
`sha256`, correctly observing that §10.4 lists no sha mismatch. That absence is an
oversight in the section I had written, not a decision: §10.4 already refuses "a `bytes`
that disagrees with the file it names", so checking a file's length but not its content is
strictly weaker than the rule beside it, and the whole point of §10.2's digest scope is
that `data_hash` identifies the data rather than the document. It is also load-bearing
downstream — Task 4's `read_frame` must "verify the file's digest before reading and refuse
a mismatch", and Task 5's `pull` must refuse an arrival that "does not match the manifest's
digests"; neither is possible against a spec that does not call a content mismatch a
refusal. Within an unreleased 0.6.0 this is an edit, not a version bump. Cost if wrong: one
refusal clause, one vector case and one branch of `verify_manifest` come back out.

Task 2 review (sonnet, e4120cf..81bd80c): spec ✅, quality Approved, no Critical or
Important. The reviewer reproduced all 20 vector cases with `hashlib` and `rfc8785` alone,
so the suite is not tautological. Two ⚠️ items resolved by me, both clean: `uv run
tools/check_vectors.py` reports exactly `lab/effects.json` and `lab/selection.json` and
nothing else, and the codes resolve to the strings `HEPH-LAB-412` and `HEPH-LAB-424`.

Ruling 15 (review Minor 1, promoted — load-bearing and security-adjacent): **§10.1 gains a
path grammar, and §10.4 the matching refusal.** `FileDigest.path` is unconstrained today,
so `verify_manifest` joins it onto `root`: an absolute `path` escapes `root` and makes
`digest_file` raise a bare `ValueError` instead of `ManifestError`, a `..` segment reads
outside `root`, and `./a.csv` and `a.csv` both survive the duplicate check. The reviewer
rated it Minor because §10 defines no grammar; that silence is the defect. Task 5's `pull`
fetches files from a remote and verifies them against a manifest that came with them, so an
unconstrained `path` is a traversal in the one function whose job is to distrust its input.
§10.1 states that `path` is a relative path using `/`, with no leading `/` and no `.` or
`..` segment; §10.4 refuses one that is not. Cost if wrong: one clause, one validator and
one vector case.

Ruling 16 (review Minor 2): the `sort-is-bytewise-over-paths` vector gains paths that
discriminate UTF-8 byte order from UTF-16 code-unit order (U+FFFF against U+10000). Why:
`conformance/` is shared by every implementation, and the current case passes for a sorter
that orders by UTF-16 code units — so the vector does not pin what §10.2 says. Cheapest to
fix before the Go and TypeScript ports read it. Cost if wrong: one vector case.

Review Minor 3 folded into the same round: `verify_manifest`'s docstring states that it
does not flag files on disk the manifest omits, so Tasks 4 and 5 cannot assume it does.

Task 2: minor (deferred): test_data_manifest.py's `data_hash` unit test recomputes through
`content_hash` and so mirrors the implementation. Acceptable — the vectors carry the
independent pin and the test file's docstring says as much — but the final review should
decide whether to pin one literal vector value in the unit test too.

Task 2: fix round 1/5 (3 addressed, 0 open — path grammar in §10.1/§10.4 with model
validation and 7 refusal vectors, the UTF-8-vs-UTF-16 sort case, `verify_manifest`'s
docstring; commits 81bd80c..8ed46b1). Re-reviewer re-derived the new sort case's
`data_hash` without importing `hephkit` and confirmed the two orders differ.
Task 2: complete (commits e4120cf..8ed46b1, review clean). 472 passed, coverage 99.85%,
mypy clean, `conformance/lab/manifest.json` at 29 cases, `check_vectors` down to the two
expected missing suites.

Ruling 17 (raised by Task 3, load-bearing): **§10.3 gains an ambiguity refusal, and
`release_as_of` refuses rather than tie-breaking.** The implementer found that §10.3 is
silent on two releases sharing the latest `published` at or before *d*, and broke the tie
by the later `release` label so the answer would not depend on input order. The
determinism was the right instinct and the tie-break is the wrong answer: `release` is an
opaque string by §10.1, so a lexical maximum is arbitrary — it picks `r9` over `r10` — and
a dated analysis that silently resolved to the wrong release is precisely the invisible
wrong answer this module exists to prevent. §10.3 says that where more than one release
shares the latest eligible `published`, resolution is ambiguous and MUST be refused; the
caller who knows what their labels mean disambiguates. This matches how §10.4 treats a
duplicate `path`: refuse rather than repair. Cost if wrong: one clause, one branch and one
test, and callers with same-day releases must pass a narrowed sequence.

Task 3 review (sonnet, 8ed46b1..9d78b1c): spec ✅, quality Approved, no Critical or
Important. Two ⚠️ items, both real:

Ruling 18 (⚠️ 1, confirmed by reading the spec): **§10.1 must declare `release` opaque.**
§10.3 now says "because `release` is opaque (10.1)", but §10.1's table row says only "The
upstream release the extractor read" — the citation points at nothing. The spec's own
convention is to state opacity outright: §7.1 says "`run_id` is opaque: implementations
MUST NOT derive meaning from its form". Without the clause, a later implementer could
reasonably sort releases by label, which is the exact thing Ruling 17 forbids. §10.1 gains
it. Cost if wrong: one sentence.

Ruling 19 (⚠️ 2, CLAUDE.md rule 1 — overrides the plan): **§10.3 gets a vectored suite,
`lab.releases`.** Rule 1 says behaviour is pinned by `conformance/` vectors and that
changing behaviour changes the spec and the vectors in the same PR. §10.1, §10.2 and §10.4
are pinned by `lab.manifest`; §10.3 alone ships normative MUSTs with nothing pinning them,
and it is pure data in, pure data out — releases and a date to a release or a refusal —
which is the same shape as `lab.selection`, vectored for exactly that reason. The plan's
Global Constraints name three vectored suites for this wave; CLAUDE.md outranks the plan,
and the asymmetry inside one spec section is the tell that the plan under-specified. The
cases need no hashing at all, so they are hand-derived trivially. Cost if wrong: one suite
file, one enum entry, one minimum and one runner.

Ruling 20: **no ADR for §10.3's ambiguity refusal.** Rule 1 asks for an ADR "if a decision
changed". Nothing changed: §10 is a new section, and a decision made inside a new section
is recorded in the spec's own "Decisions this version settles" list, which is where §10's
other decisions sit. ADR 0025 remains this wave's only ADR, and it records adopting a
dependency, which is the kind of decision the `docs/adr/` series carries. Cost if wrong: an
ADR is written later and the series is append-only, so nothing has to be unwound.

Ruling 21 (review Minor, promoted because the new vectors must carry the right codes):
`release_as_of`'s two refusals get the two codes the registry actually prescribes, mirroring
the split `manifest.py` already uses. `TemporalError` keeps `HEPH-LAB-424` for no eligible
release — the release asked for does not exist, which is 424's "required artefact is
missing". The collision raises `AmbiguousReleaseError(TemporalError)` carrying
`HEPH-LAB-412`, whose guidance is "a gate that guards research integrity refused the
operation, which usually means the gate found what it exists to find" — the data is present
and the guard fired. Subclassing keeps `except TemporalError` catching both. Cost if wrong:
one class and the `expect` field of a few vector cases.

Task 3: fix round 1/5 (1 addressed, 0 open — the ambiguity refusal replacing the
tie-break; commits bb89cce..9d78b1c).
Task 3: fix round 2/5 (5 addressed, 0 open — §10.1's opacity clause, the 424/412 split with
`AmbiguousReleaseError`, the `lab.releases` suite at 14 cases, the test renames, the
duplicate-label test; commits 9d78b1c..84e70d8). The re-reviewer judged the suite case by
case and confirmed each can fail a wrong resolver — notably that the r9/r10 pair needs both
orderings to catch both a lexical and a numeric maximum, which it has.
Task 3: complete (commits 8ed46b1..84e70d8, review clean). 499 passed, coverage 99.85%,
mypy clean. Verified myself: `check_vectors` reports exactly `lab/effects.json` and
`lab/selection.json`, so the new suite is wired into the schema enum and `MIN_CASES`
correctly.
Task 3: minor (deferred): one over-long line left by a docstring reflow in `releases.py`.
No ruff line-length config is set for this distribution, so nothing enforces it; the final
review can decide whether to tidy it.

Task 3 dispatched (sonnet), BASE 8ed46b1. Dispatch names spec §10.3 as the whole
requirement, Task 2's shipped surface, and the hindsight failure the clause exists to
prevent (a date before every release must refuse, not fall back).

Ruling 22 (raised by Task 4, correctness): **`pyarrow` joins the `data` extra and `query`
returns DuckDB's own `.pl()` frame.** The implementer fell back to
`polars.DataFrame(fetchall(), schema=columns, orient="row")` because `.pl()` needs pyarrow
and the `data` extra does not declare it — correct diagnosis, wrong resolution. `schema=`
there carries column *names* only, so every dtype comes from polars' inference over the
returned rows: an int column with a null can land as Float64, a decimal as a float, an
all-null column as Null. A query result whose types depend on which rows came back is the
silent wrongness this kit exists to prevent, and it would never raise. pyarrow is DuckDB's
documented bridge to polars and the extra already carries polars, duckdb and dvc, so one
more line is the cheap half of this trade. A test pins the dtypes through `query`. Verified
myself that pyarrow is absent from a `data`-only install (it is present in my local
all-extras venv only because `track`/`ml` pull it, which is exactly the trap). Cost if
wrong: one dependency line and a revert to the row constructor.

Task 4 concerns accepted without change, for the record: `enable_external_access = false`
after loading the manifest's files is the right shape (a bare `read_csv('/etc/passwd')` in
caller SQL is refused, and a file the manifest omits is not a table); `query` reading only
`.csv` and `.parquet` while still verifying every entry is documented in the module
docstring; the digest check not being atomic with the read is a genuine TOCTOU window and
the docstring says so, which is the honest answer for a kit whose frozen datasets are
read-only by construction.

Ruling 23: moon is not installed in this environment (`which moon` finds nothing, no
`~/.moon/bin`, and `.prototools` does not pin it), so no moon.yml change in this wave can
be executed locally — CI is the only place `moon run` happens. I read the new `test-spine`
task instead: `env:` is a documented moon task field though this is the repo's first use,
`UV_PROJECT_ENVIRONMENT: '.venv-spine'` with `--exact` is what makes the proof real (the
shared `.venv` holds every extra, so a plain `uv run` would leave them importable), and
`.venv-spine/` is in `.gitignore` with a clean `git status`. Accepted as unverifiable here
and flagged for the final review. Cost if wrong: one CI job fails on first push and the
task's syntax is corrected.

Task 4: minor (deferred): CI now builds a second environment for `test-spine`, which
relinks the PyO3 extension. Rust artifacts are shared through `target/` within the job so
the cost should be a relink rather than a full compile, but `tools/dx_budget.sh` is the
thing that would notice if not. The final review should decide whether to measure it.

Task 4 review (sonnet, 84e70d8..dcd636b): spec ✅ on signatures and behaviour, one
Important, six Minor. The reviewer reproduced the glob escape in DuckDB and independently
confirmed that `ATTACH`, `glob()`, `COPY ... TO`, `read_text` and `SET
enable_external_access=true` are all refused after the lockdown.

Ruling 24 (review Important 1, real — the fix goes at the read boundary, not in the
grammar): **no path string reaches a globbing reader.** A manifest `path` may legally
contain `*`, `?` or `[` — §10.1's grammar forbids only empty, `.` and `..` segments — and
`read_csv('x*.csv')` globs, so a manifest naming `x*.csv` pulls an unlisted `xother.csv`
into the table with no digest ever checked. That breaks the module's one promise. The
reviewer offered two fixes; I rule for the structural one. Forbidding glob characters in
§10.1 would be simpler but it outlaws filenames POSIX allows and downloads routinely
produce (`report[1].csv`), and it would only protect readers that remember to check.
Opening the verified file and handing the reader a handle instead of a pattern removes the
class for every future reader, and verification already works on exact paths
(`digest_file` opens bytes and never globs). Cost if wrong: the loaders hold a file handle
where they held a path.

Ruling 25 (review ⚠️, real and introduced by this task): **`typecheck` gets the same extras
as `test` and `test-fast`.** `moon run hephkit-lab:test-fast hephkit-lab:test-spine
hephkit-lab:typecheck` runs tasks concurrently, and this task made `test-fast` sync the
shared `.venv` *with* extras while `typecheck` still runs a plain `uv run` on that same
`.venv` — so one task can resync the environment out from under the other. Before this
task both used the same plain `uv run` and could not disagree. `test-spine` is safe because
it has an environment of its own. Giving `typecheck` the same `--extra` flags makes all
three agree about the shared environment, and it also typechecks the extras code against
real libraries rather than against ignore-missing-imports overrides. Cost if wrong: a
slightly slower typecheck.

Task 4: minor (deferred): the commit message of dcd636b says an integer column with a null
"could land as Float64"; polars row inference generally keeps Int64 there, and the real
failures were the all-null `Null` dtype and Decimal. The claim is overstated but the change
is right; not worth rewriting history for.

Task 4: fix round 1/5 (2 findings + 5 folded minors addressed, 0 open — handle-based
loading so no manifest path reaches a globbing reader, `typecheck` given the same extras,
escape tests for ATTACH/glob/COPY/SET, a parquet tamper test, the no-relation guard, the
case-collision test, the `.gitignore` comment; commits dcd636b..12994dd). The re-reviewer
reproduced the bug and the fix on duckdb 2.0.0: `pl.read_csv("<dir>/x*.csv")` returned
`[1, 2, 99]` while `pl.read_csv(handle)` returned `[1, 2]`, and the handle read keeps
DuckDB's date typing, so the implementer's reason for not round-tripping through polars
holds.
Task 4: complete (commits 84e70d8..12994dd, review clean). 523 passed with extras, coverage
99.86%, `test-spine` 498 passed with 22 deselected in an environment where duckdb does not
import. Verified myself what the re-reviewer could not see in its diff: all four moon tasks
agree on the environment — `test`, `test-fast` and `typecheck` each carry
`--extra data --extra causal --extra stats`, and `test-spine` alone runs `--exact` with
none, so Ruling 25's race is closed.
Task 4: minor (deferred): the report's first "Implemented" section still describes the
`fetchall()` construction that two later commits replaced. Documentation staleness inside a
workspace file, not a defect in the branch.

Task 4 dispatched (sonnet), BASE 84e70d8. Dispatch carries the `_extras` path, that
`test_extras.py` already exists, and that this is the task establishing the extras pattern
three later tasks copy: extras in the coverage-measuring moon task, a `test-spine` task
with none, and a registered `extras` marker. It is told to report how many tests
`test-spine` actually ran, since one that passes by skipping everything proves nothing.

Ruling 26 (Task 5 concern 2, correctness of error semantics): **only a digest mismatch is
412; a DVC failure to obtain the snapshot is 424.** The implementer mapped every
`DvcException` during `pull` to `ManifestError` (412), whose registry guidance is "a gate
that guards research integrity refused the operation, which usually means the gate found
what it exists to find". A remote that is unreachable, or an object that is not in it, is
not that — and labelling it 412 sends a researcher hunting a corruption that does not
exist, which is worse than an unhelpful error. 424 is "Required record, manifest or frozen
input is missing... Nothing was half-done; the dependency is absent rather than corrupt",
which is exactly a failed fetch, and `MissingManifestError` already carries it. So: fetch
failures become `MissingManifestError` naming the remote, verification failures stay
`ManifestError`, and anything genuinely unexpected propagates unchanged. The local
directory remote this wave tests against makes the distinction invisible today, which is
precisely why it has to be right before a real remote arrives. Cost if wrong: one `except`
clause.

Ruling 27 (Task 5 concern 5): `data/__init__.py` re-exports the snapshot and card names.
The plan's File Structure makes that file "the public surface of `lab.data`: manifests,
releases, loaders, snapshots", so this is a plain gap, not a judgment call.

Ruling 28 (Task 5 concerns 3 and 4): the uncovered "arrived as a link" refusal gets a test —
it is one of the two branches protecting a destination from bytes that came off a remote,
and an untested guard is a guard that can be deleted by accident. The `files/md5` pointer
layout stays, since bridging SHA-256 to DVC's md5 object ids needs some pointer and this one
is validated as untrusted, but the assumption on DVC 3's layout must fail loudly with a
message naming it rather than raising an opaque `KeyError` three frames down, and the module
docstring must say the coupling exists. Cost if wrong: a test and an error message.

Task 5 review (sonnet, 12994dd..a6eaa11): spec ❌ on one point, three Important, seven
Minor. Core safety properties confirmed sound: nothing lands unless it verifies, every
destination is resolved before any write, links are refused even when their bytes match,
the card carries every `Manifest` field (checked against the model, not the report), and
the `except` was not widened.

Ruling 29 (amends Ruling 26, prompted by review Important 1): **a pointer that is present
but malformed is 412, not 424.** My earlier wording said "a failed pointer read must be
424", and the implementer split it more finely than that: absent or unobtainable pointer →
424, garbled pointer content → 412. The finer split is the correct one and my ruling was
the loose one. `spec/errors.yaml`'s 424 guidance says it outright — "If the artefact exists
but says the wrong thing, the code is HEPH-LAB-412" — so a pointer that exists and lies is
exactly 412. The code stands; the tests must assert which code, which they currently do
not. Cost if wrong: one `raise` and one assertion.

Ruling 30 (review Important 2, real gap): **`OSError` around the pointer fetch maps to
424.** Only `DvcException` and `FileNotFoundError` are caught today, and the single
unreachable-remote test uses an unknown URL scheme that dies at DVC config time. A genuinely
dead host surfaces from `odb.fs.cat_file` as `OSError`, `ConnectionError` or a provider
exception, none of which is a `DvcException` — so the one failure mode Ruling 26 exists to
label correctly is the one that would escape raw. Catch `OSError` narrowly around that call
only, never `Exception`. Cost if wrong: one `except` clause and a monkeypatched test.

Ruling 31 (review Important 3): every refusal test asserts `.code`, not just the exception
class. `MissingManifestError` subclasses `ManifestError`, so `pytest.raises(ManifestError)`
passes for a 424 as readily as a 412 — three of the refusal tests therefore cannot tell the
two apart, which makes them unable to catch a regression in the very split Rulings 26 and 29
are about.

Task 5: minor (deferred): `MissingManifestError(ManifestError)` has 424 subclassing 412,
while `AmbiguousReleaseError(TemporalError)` in `releases.py` has 412 subclassing 424 — the
two modules order their hierarchies in opposite directions. Each is locally sensible (the
general class first, so one `except` catches both) and neither is a correctness bug, but a
caller writing `except ManifestError` for corruption will also swallow absence. The final
review should decide whether the public surface wants one convention.

Task 5: fix round 1/5 post-review (3 Important + 6 Minor addressed, 0 open — the `OSError`
mapping around `cat_file`, `.code` assertions through a `refused()` helper, E305, `fullmatch`,
the `_place` cleanup test, the anchored warning filter, the weakened assertion, the docstring
disclosure; commits a6eaa11..17d57c8). The re-reviewer verified the three sequential `try`
blocks in `_read_pointer` really are separate, closing the path where a 424 (a `ValueError`
subclass) was being caught by the parse handler and relabelled 412 — a bug the new test
caught in the implementer's own first attempt.
Task 5: complete (commits 12994dd..17d57c8, review clean). 548 passed, coverage 99.74%,
mypy clean, `test-spine` 503 passed with 42 deselected. `lab.data` is finished: manifests,
releases, loaders, snapshots and cards.

Task 5: minor (deferred): the `OSError` → 424 mapping is applied around the pointer read but
not around `repo.pull()` in `_fetch`, so a host that answers the pointer read and then fails
mid-fetch could still surface a raw `OSError`. Deferred rather than rounded again because a
dead host fails at the pointer read, which is the first remote touch and is now covered, and
DVC wraps most transport failures in `DvcException`, which `_fetch` already maps to 424. The
final review should decide whether to close the symmetry before a real remote is used.
Task 5: minor (deferred): the `DvcException`-from-`cat_file` branch (snapshots.py:168-169)
has no test; coverage is 99.74% and the gate is 90%.

Task 5 dispatched (sonnet), BASE 12994dd. Dispatch carries the local-directory-remote
ruling, Task 4's extras/marker shape, and the symlink hazard below — asked as a decision to
make and justify in the report, not as a prescription, since `pull` may not be the right
home for it.

Task 6 review (sonnet, 17d57c8..1ffadea): spec ✅, no Critical or Important, five Minor.
The reviewer recomputed the pinned key from the JCS text with `hashlib` alone and matched
it, and confirmed the write ordering is crash-safe: body first, sidecar last, each through
`mkstemp` + `os.replace`, and `_lookup` treats a body with no sidecar as a miss, so there
is no half-served state. One ⚠️ resolved by me: `hephkit.errors` does export `LAB_412`,
`LAB_422`, `LAB_424` and `LAB_409` (imported and printed them), `check_modules.py` is green,
and `check_vectors.py` reports exactly the two expected missing suites.
Task 6: complete (commits 17d57c8..1ffadea, review clean). 566 passed, 99% coverage, spine
521 passed, mypy clean.

Task 6: minor (deferred), all five, none of which can serve a wrong answer — the reviewer
notes each fails safe, which is why they stay out of the loop:
- `read_text`/`read_bytes` catch only `ValueError` and `FileNotFoundError`, so a sidecar
  that is a directory or a permission error escapes as a raw `OSError` rather than
  `CorruptSourceError`. Arguably correct for a local filesystem fault, unlike the remote
  case in Task 5.
- `frozen()` lists presence without checking digests, and trusts the sidecar's `key` field
  rather than its filename, so a renamed sidecar would report a key that does not match its
  file. Either document presence-only or compare the stem to the key (one line).
- No `fsync` before `os.replace`: a power loss can leave a zero-length body, which the
  digest check turns into `CorruptSourceError` rather than a bad serve. Undocumented.
- The failed-write test patches `os.replace` to fail on the *first* write, so it never
  reaches the "body written, sidecar write fails" state — which is the state the module's
  ordering argument rests on. Worth pinning: fail only the second replace, then assert
  `frozen() == ()` and that the next offline fetch raises `SourceError`.
- Method and URL are hashed verbatim with no normalisation (`GET` and `get` differ);
  defensible but undocumented.

Ruling 33 (Task 11, correcting my own dispatch): **all ties is a defined 0.0 for Cliff's
delta, not a refusal.** My dispatch told Task 11 that "n = 1, zero variance, or all ties"
must refuse in all three statistics; the implementer refused the first two and returned
`0.0` for all-ties delta. The implementer is right and I over-generalised. Cliff's delta is
`(#(x>y) - #(x<y)) / (nx*ny)`: with all ties the numerator is zero and the denominator is
not, so zero is the published definition's answer and it means something — no dominance
either way. Only Cohen's *d* divides by a quantity that vanishes. The plan's own Review
Focus item 5 attributes the hazard to "Cohen's *d* ... and a bootstrap", not to delta, so
the implementation matches the plan and my dispatch was the loose restatement. Cost if
wrong: one branch and one vector case.

Task 11: minor (deferred, and it belongs to Task 4's code, not Task 11's): `ruff check`
reports F841 at `data/frames.py:99` — `relation` assigned and never used. It is a **false
positive with a real hazard behind it**: the name is consumed by DuckDB's replacement scan
inside the f-string `FROM relation`, which an earlier re-reviewer also flagged as an
implicit coupling to a local variable name. So the query's correctness depends on a binding
that a linter actively recommends deleting. No ruff gate is enforced in CI, so nothing fails
today. The fix for the final review's wave: build the table from the relation object itself
(for example `relation.create(...)`) instead of interpolating its local name into SQL, which
removes both the lint and the coupling.

Task 11 review (sonnet, 1ffadea..ce82811): spec ✅, Approved, no Critical or Important. The
reviewer recomputed all thirteen value cases in an isolated stdlib-only `python3 -I` script
with no `hephkit` import and reproduced every one, and judged each for whether it
discriminates — naming the unequal-size case as the one that catches unweighted variance
averaging (-1.633 instead of -√3) and the tie case as the one that catches ties taken as
half-credit or dropped from the denominator.
Task 11: complete (commits 1ffadea..ce82811, review clean). 610 passed, 99% coverage, spine
564 passed, mypy clean. Verified the ⚠️ myself: `check_vectors.py` now reports exactly one
missing suite file, `lab/selection.json`, which Task 12 writes.

Task 11: minor (deferred to the final review's fix wave, not rounded here — batching the
branch's small items into that one wave costs less than a dedicated round per task):
- **Worth fixing, not just considering:** no test covers one constant sample against one
  varying sample (`[2,2,2]` vs `[1,2,3]`), which must return a finite *d*. The `and` at
  stats.py:501 is what makes it finite, and a mutation to `or` would wrongly refuse a
  legitimate comparison — a constant control group against a varying treatment is a case
  researchers actually hit, so this is an input class with no test rather than a style note.
- The module docstring does not say the statistics are descriptive rather than inferential,
  that *d* and *g* assume a roughly common variance, or that the *g* correction is the
  standard approximation and not the exact gamma-function factor.
- The `g-unequal-sizes-eight-elevenths` case's `derivation` prints a trailing digit that
  disagrees with its own `expect` (`…5471` against `…547`). Harmless under the tolerance,
  but a reader comparing the two will see them differ.
- Noted, no action: the bool/str/bytes validation and the underflow guard are surface beyond
  the brief that the next two tasks inherit (tested and defensible); `cliffs_delta` is
  O(n_a·n_b), which Task 13's bootstrap may want sorted, and must not be pre-built.

Task 12 reported NEEDS_CONTEXT before writing any code, correctly: the plan's decision
table has two combinations it assigns no test to, neither of which is one of its three
named refusals.

Ruling 34 (plan defect in the decision table — the two gaps get different answers, because
they are different kinds of gap):
- **Ordinal with three or more groups, unpaired → `kruskal_wallis`.** The table already
  routes "three or more interval groups, non-normal" there, and Kruskal-Wallis is a rank
  test: ordinal data with three or more independent groups is its canonical use, not an
  extension of it. The table's "interval" in that row is the loose word, not the boundary.
  Refusing a design with a single universally-agreed answer would be a false refusal, and a
  selector that refuses what a researcher legitimately needs teaches them to bypass it —
  which costs more than the omission it protects.
- **Any paired design with three or more groups → refuse.** The parametric answer is
  repeated-measures ANOVA and the non-parametric one is Friedman, but `TestRequest` carries
  scale, groups, paired, normal, equal_variance and n_min, and **nothing that can express
  sphericity**. Naming a repeated-measures test would assert an assumption the request
  cannot state, which is exactly the failure `choose_test` exists to prevent, so the honest
  answer is a refusal whose message says the table covers no repeated-measures design.
  Refusing here is not the table's omission leaking through; it is the request type being
  too small to carry the choice.
Why the split rather than one blanket answer: extend where the answer is unambiguous and
already half-present in the table, refuse where choosing would assert something unexpressed.
Cost if wrong: one table row and one refusal branch, each with its vector case.

Ruling 35 (Task 12's side note): `groups < 2` is the one-group/zero-group refusal, which
covers negatives too, and `TestRequest` constrains `groups` and `n_min` to be non-negative
at the model so impossible values are refused by construction rather than reaching the
table. Model-level validation for values that cannot exist, `StatsError` for a well-formed
request the table cannot serve.

Task 12 review (sonnet, ce82811..1e8cad5): spec ✅ against the table and both rulings —
every row implemented, none dead, no refusal misfiring, Fisher boundary right on both sides
— plus three Important findings about what the table still does not settle.

Ruling 36 (review Important 1, a third gap in the plan's table): **three or more interval
normal unpaired groups with `equal_variance=False` get `welch_anova`, not `one_way_anova`.**
This is worse than the sphericity gap: there the request could not express the assumption,
here the caller *did* express it and was handed a test that assumes the opposite. The table
already draws exactly this distinction two columns over — equal variance → `independent_t`,
unequal → `welch_t` — so silently dropping it at three groups is the anomaly, not the
extension. Welch's ANOVA is the standard answer and `equal_variance` is a field the request
carries, so nothing is being asserted that the caller did not state. By Ruling 34's
principle this is a gap-1 case (extend where the answer is unambiguous and half-present),
not a gap-2 case (refuse where choosing would assert the unexpressed). Cost if wrong: one
row and one vector case.

Ruling 37 (review Important 2, accepting the reviewer's own analysis against my framing of
the question): **`fisher_exact` keeps the row for every nominal group count; the defect is
the words, not the routing.** I had asked whether naming it for a three-group design asserts
a 2×2 structure. The reviewer's answer is better than my question: `TestRequest` carries
`groups` and `n_min` and nothing about outcome categories, so it cannot describe a 2×2 table
at *any* group count — even `groups=2` could be 2×k — and `chi_square` is chosen under the
same blindness at `n_min >= 5`. Refusing would turn away designs researchers legitimately
run (R's `fisher.test` handles r×c). So the row stands, and what gets fixed is that the
`reason` never says the exact test applies to the whole table with the Freeman–Halton
generalisation beyond 2×2 — a reader who pipes the bare name into
`scipy.stats.fisher_exact` hits a 2×2-only error. The reviewer also caught a real
documentation error alongside it: `n_min` is described as the smallest *cell* count, but the
rule of 5 is about *expected* counts.

Verified myself, both ⚠️ items: `ruff check --select I` does flag the import order in
`test_stats.py` (one error, fixable) though no `[tool.ruff]` config is set for this
distribution, so nothing enforces it today; and `mypy --strict` runs against `src` only, so
the `# type: ignore[misc]` in the tests is never evaluated by the gate either way.

Task 12: fix round 1/5 (3 Important + 6 Minor addressed, 0 open — the `welch_anova` row,
the Fisher wording and `n_min` expected-count correction, five new vectors, the import order,
the McNemar/Cochran wording, the sphericity regex, the full reason assertion, the
`_rank_outcome` helper, the dropped ignore; commits 1e8cad5..881f6ce). The re-reviewer
re-derived the dispatch order after the insertion and confirmed the only changed outcome is
the intended one: `welch_anova` sits inside `groups >= 3 and interval and normal`, so
non-normal and ordinal three-group requests still reach `kruskal_wallis` before variance is
read, the paired refusal still precedes every scale test, and the two-group variance rows
are untouched.
Task 12: complete (commits ce82811..881f6ce, review clean). 644 passed, `stats.py` 100%,
`hephkit.lab` 99%, spine 599 passed, mypy clean, and `check_vectors.py` green at exit 0 —
the first commit in the wave where all three stamped suites exist.

Task 12: minor (deferred to the final review's fix wave):
`test_a_request_with_an_unknown_member_is_refused` validates a payload carrying `"scale":
"interval"` as a string, which `strict=True` rejects on its own — so the test may pass for
the wrong reason and `extra="forbid"` is effectively unpinned. Predates the fix round.

Ruling 38 (Task 13 concerns 1 and 2 — the coverage test): **the band stays at nominal
±0.02 and the implementation earns it; the estimator moves to BCa.** The implementer
disclosed, correctly and unprompted, that it redesigned the test after seeing a number: a
first design (n=30, 400 replicates, band set before measuring) came out at 0.92, a
2000-replicate check put the true rate near 0.938, and it then moved to n=100 with 1000
replicates and a ±0.02 band, measuring 0.932. Two different things happened there and they
get different answers. Growing n from 30 to 100 is legitimate — percentile-bootstrap
under-coverage at n=30 is a known property of the method, not a defect in our code, and the
design's claim ("approximately the nominal rate") is an asymptotic one, so a larger n
measures the property actually claimed. Choosing a band that clears a measured value is not
legitimate, and 0.932 against a floor of 0.93 is 0.002 of headroom against a Monte Carlo
standard error of about 0.007 — a test that will flip on any scipy change without a defect
behind it. The right fix is the estimator, not the goalpost: scipy's `method="BCa"` is
bias-corrected and accelerated and brings actual coverage close to nominal, which is what
the design asks our function to deliver. So BCa, band held at ±0.02, and if BCa cannot
reach it the numbers come back to me rather than the band moving. Cost if wrong: a slower
bootstrap and a ruling on a theory-justified wider band.

Ruling 38 is **withdrawn on its premise, and I was wrong.** It assumed the 0.932 came from a
percentile bootstrap and told Task 13 to move the estimator to BCa. The implementer checked
and corrected me: `method="BCa"` was already there in 5d57a57 (stats.py:402), so the
measurement was BCa's and there was no estimator to move. Verified myself with `git show
5d57a57:...stats.py`. What survives from Ruling 38 is only its principle — fix the
estimator, not the goalpost — and with the estimator already correct that principle now
points somewhere else, which is Ruling 41.

Ruling 41 (replaces the surviving half of Ruling 38): **the coverage band is derived from
the test's own Monte Carlo standard error, not chosen.** The remaining problem is real and
partly mine: Ruling 40 demanded the test leave the `slow` marker and fit a couple of
seconds, which forced replicates from 1000 down to 400, which raised the Monte Carlo SE
to about 0.011 — so a ±0.02 band is only ±1.8 SE and would land outside with no defect
behind it roughly one run in five. A band picked as a round number is the thing I objected
to in the first place; the fix is to stop picking it. The test computes its own tolerance as
nominal ± 3·sqrt(p(1−p)/R) — 0.033 at 400 replicates — with the arithmetic in a comment, so
the band is a function of the design rather than of the result, and a later change to
replicates moves it automatically. It still discriminates every realistic failure: returning
the sample's min and max, or any half-width error, lands far outside 3 SE. Measured 0.940
passes with about 0.9 SE of room. Cost if wrong: a tolerance expression in one test.

Ruling 39 (Task 13 concern 3, checked against the installed library): **pass `rng=` and
raise the `stats` extra to `scipy>=1.15`.** The implementer passed
`random_state=numpy.random.default_rng(seed)` to stay compatible with the extra's
`scipy>=1.14` floor. But the installed scipy is 1.15.3 and `inspect.signature` on
`scipy.stats.bootstrap` lists `rng` with no `random_state` — the old name survives only
through scipy's transition decorator, which deprecates it. This distribution runs
`filterwarnings = ["error"]`, so a scipy that starts warning turns the whole module's tests
red for no reason. Raising the floor one minor version is cheaper than carrying a
deprecated alias into a warnings-as-errors suite.

Ruling 40 (Task 13, not raised by the implementer — I found it reading what it marked):
**the coverage test must not be marked `slow`.** CI runs `moon run hephkit-lab:test-fast`,
which deselects `slow`, so the single test that proves this module's only real contract
would never run on a pull request. It is `extras`-marked, which is correct, and it should
stay in the normal suite at a couple of seconds. If BCa makes it too slow for that, cut
replicates rather than hiding it behind a marker CI skips.

Task 13 review (sonnet, 881f6ce..ef9d4ba): spec ✅, Approved, no Critical or Important. The
reviewer worked out what the coverage test actually catches rather than taking the band on
trust: min/max of the sample gives ≈1.0 and fails, a point estimate gives 0 and fails, a 90%
or 99% level fails, a half-width off by ≥12% fails, and a centre bias of ≥0.75 SE fails —
while a 10% half-width error or a 0.5 SE bias passes. So the test separates "computes an
interval" from "returns two numbers" and catches gross defects, which is what the design
asks of it; it cannot catch subtle ones, which is the honest cost of 400 replicates at 3 SE.
Task 13: complete (commits 881f6ce..ef9d4ba, review clean). 681 passed, `lab` coverage
99.63%, `stats.py` 100%, spine 627 passed, mypy clean, `check_vectors` silent at exit 0.
`lab.stats` is finished, and with it every module of this wave that is not blocked on the
CausalPhylo licence.

Resolved the review's ⚠️ myself (the reviewer's sandbox refused the command): the
`# pragma: no cover` on the finite-interval backstop is justified. I ran `bootstrap_ci` with
a statistic returning `math.inf` whenever a resample held two or more zeros — the case the
reviewer named as possibly reaching it — and scipy's BCa raised first, which the module
promotes to `StatsError` ("the statistic has a degenerate bootstrap distribution: The BCa
confidence interval cannot be calculated"). The backstop is genuinely behind scipy's own
refusal. The pragma's comment should say that this was checked rather than assumed.

Task 13: minor (deferred to the final review's fix wave):
- The pragma comment claims "no statistic is known to reach here"; it can now say the `inf`
  path was tried and scipy refuses first.
- `test_stats.py`'s module docstring still says "No test is marked `extras`" and describes
  the file as effect sizes only — both false after three tasks grew it.
- `__all__` exports `mean`, a `statistics.fmean` alias needed only as a default argument, so
  `import *` publishes it; it also collides visually with `SeedSummary.mean`.
- `sorted(values)` raises a bare `TypeError` on non-comparable keys rather than `StatsError`;
  keys are documented as ints but never checked.
- `warnings.catch_warnings()` mutates process-global state and is not thread-safe — fine for
  the lab, worth a docstring line.
- Two test comments overstate their precision (the 0.3% miss-rate claim assumes exactly
  nominal coverage), and one assertion bound is loose.
- Structural recommendation, not a defect: `stats.py` is 451 lines and reads as three
  sections — effect sizes, selection, bootstrap — over one shared validation layer. The plan
  put them in one file; if it grows again, split it into a package with `__init__`
  re-exports. The final review should decide whether to do it now.

Task 15 review (sonnet, ef9d4ba..8d03563): spec ✅, Approved, one Important, four Minor.
The reviewer checked roughly twenty page claims against the source line by line — signatures,
error codes, which extra each needs, the verify-then-read ordering, the refusals-before-scipy
ordering — and all held. It also reasoned out both import-probe tests and found two
independent mechanisms by which a module-scope heavy import fails them: a fresh subprocess
whose `sys.modules` cannot be masked, and `sys.modules[name] = None` poisoning that bites
even where the extras are installed. The probe is not vacuous.

Ruling 42 (review Important 1): **the pages lead with the extra, and `lab.track` is fixed in
the same commit.** `MissingExtraError` tells a reader to install `hephkit-lab[data]`; the
pages told them `uv add polars duckdb pyarrow dvc`. Two sources of truth for one dependency
set, and the bare list silently drops the floors the extras carry — this diff itself moves
scipy from 1.14 to 1.15 and adds pyarrow, which the page's list would not have tracked. The
extra is authoritative because it is what the error names and where the floors live. The
reviewer noted `lab.track.mdx` already uses the bare pattern and said that is a reason to fix
all three at once rather than repeat it; I agree, and I am extending the fix to `lab.track`
even though it is Wave 1's page: it is two lines, and leaving two conventions in one
directory is worse than touching a neighbouring page. Cost if wrong: a docs revert.

Ruling 43 (review Minor 1, promoted): the `lab.data` page's example must not print
environment-dependent output. Its `decimal[38,0]` dtype is DuckDB-version-specific and its
box-drawing table is polars-version-specific, so a dependency upgrade makes the page wrong
with nothing failing — the silent-staleness hazard, in the one place we promise the examples
run. Cast the aggregate so the output is a plain number.

Task 15: minor (deferred to the final review's fix wave):
- `test_package.py`'s `LAB_MODULES` is a hardcoded tuple, so a future lab module is not
  covered until someone adds it, and the error-naming half covers four of the six functions
  that call `require` (not `pull`, not `aggregate_seeds`).
- The reviewer did not source-check `choose_test`'s table rows or the effect-size formulas on
  the `lab.stats` page (stats.py:163-330); those rest on the implementer's claim that the
  printed output matched. Task 12's and Task 11's own reviews covered that code, so this is a
  spot-check the final review may want rather than a gap.

Task 15: fix round 1/5 (1 Important + 2 Minor addressed, 0 open — the install lines leading
with the extra on all three new pages plus `lab.track`, the plain-number aggregate, the
trailing blank line; commits 8d03563..732ddd5). The re-reviewer confirmed the new install
command is right for this layout, that `12` follows from the page's own CSV, and that the
implementer's unprompted correction to `lab.track.mdx` was accurate: that page claimed
`lab.track` "names `MissingExtraError`", which `track.py` does not use — it catches the
import and warns with a `RuntimeWarning` naming the extra.
Task 15: complete (commits ef9d4ba..732ddd5, review clean).
Task 15: minor (deferred): edited prose in `lab.data.mdx`, `lab.stats.mdx` and
`lab.track.mdx` was not re-wrapped to the directory's ~80-column house style. Cosmetic.

Final whole-branch review dispatched (opus), eae2e1e..732ddd5, 24 commits, 380 KB package.
Pointed at this ledger for two jobs: triage every deferred minor into fix-before-merge or
ship, and audit the rulings that changed the spec or the public surface rather than a local
detail. Told it in terms what is deliberately absent (`lab.causal`, its ADR, the causal
gate, its docs page) so the blocked half of the wave is not reported as missing work.

Final whole-branch review (opus, eae2e1e..732ddd5): **Ready after the Important findings.**
No Critical. Six Important, nineteen Minor, every deferred minor triaged, every ruling
audited — all 43 stand, with Ruling 5 flagged as not swept all the way through (see Ruling
44). The reviewer read the module sources whole from the worktree rather than as hunks, ran
five focused checks against stated doubts, and source-checked the `lab.stats` page's
selection table row by row, which Task 15's reviewer had left unchecked. All ten rows, three
refusals and three formulas match.

Ruling 44 (final review Important 1 — a plan line Ruling 5 should have swept): **drop
`--extra causal` from all three moon tasks and the CI step.** Task 4 Step 4 prescribed
`--extra data --extra causal --extra stats` verbatim, written when the plan expected Tasks
7–10 to land. Ruling 5 removed that expectation and nobody revisited the line, so every CI
run of an MIT distribution now installs `causalphylo 0.1.0` — the exact non-commercially
licensed release whose relicensing the user made a **precondition of adoption**. Nothing on
the branch imports `dowhy`, `causallearn` or `causalphylo`, and no test is `extras`-marked
for `causal`. The extra goes back in Task 7, beside the `License-Expression` gate that was
always meant to guard it. Cost if wrong: one flag per task, and a CI-time saving either way.

Ruling 45 (Important 2 — the one correctness bug on the branch): **`captured_at` and
`published` refuse a non-string input, and §10.4 gains a type-mismatch refusal.** Only
`FileDigest` sets `strict=True`; `Manifest`, `Release` and `Request` do not, so pydantic's
lax mode accepts a number for a date field. The reviewer verified against the installed
pydantic: `captured_at` as an int is accepted and becomes 1970-01-01, and `published=0`
likewise. §10.1 says "with the type given" and gives `captured_at` as an RFC 3339
`full-date` string. For `published` this is worse than a corrupt field: it is the only thing
§10.3 orders releases by, so a table whose `published` arrived as a number resolves every
date against 1970 and `release_as_of` returns a release with no refusal — hindsight in the
sampling frame arriving through the type system, which is precisely the plan's Review Focus
item 1. Fix with a `mode="before"` validator on both (wholesale `strict=True` would reject
the JSON string form that is required), and add the §10.4 clause so the next implementation
is told rather than left to infer it from §10.1's preamble. Cost if wrong: two validators
and one spec sentence.

Ruling 46 (Important 3 — take the complete fix, not the minimum): **all three new modules
adopt Wave 1's error shape, and the rule is written down.** Wave 1 settled this: a module
base plus a `Missing*` subclass for absence (`ConfigError`/`MissingConfigError`,
`GateError`/`MissingSubjectError`). This wave produced three shapes — `manifest.py` matching
it, `releases.py` inverted (the absence code as the base), and `sources.py` with two
unrelated classes. The `sources.py` one has a behavioural cost: there is no single `except`
for "this frozen input is unusable", and because the two sit under different builtin bases,
`except LookupError` silently misses corruption. The reviewer's argument for doing it now
rather than later is the one I find decisive: this is the wave whose stated purpose is to
prove the contract *before eleven modules lean on it*, all three modules are `experimental`
and unpublished, and the next module will copy whichever shape it meets first. So: a base per
module, the 424 absence named for the absence, and the convention recorded in
`lab/__init__.py`'s docstring. Cost if wrong: a rename across three modules and their tests,
with no vector change since vectors assert codes and not class names.

Ruling 47 (Important 4): **`_sample` accepts any non-str/bytes iterable and `numbers.Real`.**
The reviewer verified that a polars `Series` and a numpy array are not
`collections.abc.Sequence`, so `cohens_d(frame["a"], frame["b"])` — the obvious composition
of the two modules this wave shipped — is refused, and so is `.to_numpy()`, and so is
`list()` of an integer numpy array because `np.int64` is not `int`. It fails safe, which is
the right direction, but a wave whose goal is an analysis driven end to end through the spine
cannot have its own loader unable to feed its own statistics. Widen the type gate and keep
the explicit `bool` and non-finite refusals exactly as they are. Cost if wrong: a narrower
gate and a remedy in the message instead.

Ruling 48 (Important 5): **`lab.stats.mdx` stops printing exact bootstrap bounds.** Ruling 43
removed this hazard from `lab.data.mdx`; the same page one file over prints
`low=0.77 high=0.8` and `Interval(low=0.765, high=0.805, ...)`, which are BCa output over
scipy's resampling order and numpy's RNG stream. The page does exactly what its own module
docstring says a vector must never do. Print rounded values, or only the properties the page
teaches. Cost if wrong: a docs revert.

Ruling 49 (Important 6): **§10.4 states which refusals are decidable from the document alone
and which need the dataset root, and the availability caveat goes on the `bytes` clause too.**
Ruling 13 added the sha256 sentence with "where that file is available to check" beside an
existing `bytes` sentence without it — two checks of the same class in adjacent sentences,
caveated asymmetrically. The code gets the layering right and says so in a docstring, but
`conformance/` and the spec are what the Go and TypeScript ports read, and a reader of §10.4
alone would build a document validator asked to refuse a mismatch it has no files to check.
Presentational, moves no requirement. Cost if wrong: one sentence.

Ruling 50 (Minor 1 — and it corrects my own earlier suggestion): **use
`connection.register`, not `relation.create`.** My Task 11 ledger note proposed
`relation.create(...)` as the fix for the `relation` replacement-scan coupling. The reviewer
tested it on duckdb 2.0.0: `create()` does not quote its argument, so `create('raw/a.csv')`
fails with "Schema with name raw/a does not exist" — which would break every manifest with a
path in a subdirectory, the shape the docs page itself uses. Register the relation under a
fixed internal name and keep the existing quoted `CREATE TABLE`, then unregister. Cost if
wrong: the coupling returns.

Ruling 51 (Minor 14): **broaden `HEPH-LAB-422`'s title and hint rather than add a fifth LAB
code.** Ruling 2 kept `StatsError` on 422 as the least-bad fit, and the reviewer is right
that the consequence is reader-facing: the registry entry is titled "Experiment config failed
validation" with a hint naming "the experiment configuration", so a researcher whose
bootstrap was refused is sent to a page about config files. Broadening the title to cover a
request or sample a statistic cannot serve keeps the code count down and fixes the
inaccuracy; a new code would be more precise but is surface the constraint tells us not to
add without need. Regenerate `_codes.py` and the error pages. Cost if wrong: a fifth code
later, which the registry is append-friendly about.

Ruling 52 (Minor 15): the vector-file schema makes `source` **required**. All nineteen files
carry it and CLAUDE.md rule 2 is what makes it mandatory in practice; this branch added four
suites that all carry it, so it is the natural place to turn an observed convention into an
enforced one. Cost if wrong: one schema line.

Ruling 53 (Minor 16, deferred with reasons): **leave `derivation` inside `input` for now.**
The reviewer is right that prose an implementation must learn to discard sits in the member
it unmarshals, and that a case-level `derivation` would be cleaner. But the case object is
`additionalProperties: false` across *every* suite including Wave 1's, so fixing it properly
means a schema change plus touching roughly thirty cases in this wave's files and deciding
what to do about the older suites. That is one coherent change for all suites, not a tail-end
edit to this branch. Recorded here so it reaches a human rather than dying. Cost if wrong: the
Go and TypeScript ports each carry a drop-unknown-key rule until it is done.

Deferred-minor triage accepted as the reviewer graded it. Shipping without change: the
`data_hash` unit test recomputing through `content_hash`; the over-long line (and the whole
line-length class — no `[tool.ruff]` config exists anywhere, so there is no standard to judge
against, and the item is dropped rather than carried); the second CI environment's relink cost
(unmeasurable by reading — measure with `tools/dx_budget.sh` after the first real CI run); two
stale commit messages and one stale workspace report; the untested
`DvcException`-from-`cat_file` branch; `OSError` escaping `read_text`/`read_bytes` as a local
filesystem fault; no `fsync` before `os.replace`; `sorted(values)` raising `TypeError` on a
non-int key against a `Mapping[int, float]` contract; `catch_warnings` thread-safety; two
overstated test comments and one loose bound; and splitting `stats.py` into a package, which
the reviewer and I both read as churn on a file three tasks just settled — revisit at a fourth
section.

Fix wave dispatched (opus): all six Important findings and seventeen Minor ones in one
subagent, per the final-review protocol. There is no second wave; residual findings get
adjudicated and surfaced.

Fix wave (opus) applied all six Important and seventeen Minor findings in ten commits,
732ddd5..f451c84. Its first run was cut off mid-flight by a network error on the API, with
four commits landed and six source files uncommitted; it was resumed with the state I could
see from the worktree and told to re-read its own uncommitted diff rather than trust its
memory of it. Final verification: 723 lab tests at 99.69% coverage, spine 665, mypy clean,
four repo checkers silent, five generators `--check` clean, `tools/tests` 407 passed, docs
build with 17 bun tests, link checker, and `examples/lab-replay/gate_test.sh` passing.

Three corrections the fix wave reported rather than implementing blindly, all accepted:
- Important 2's `sources.Request` had no affected field — its only laxness is `str` → UTF-8
  `bytes`, which it judged a lossless reading, so it changed nothing there.
- Minor 11's premise was wrong: the `derivation`'s `-1.2596733145955471` and the `expect`'s
  `-1.259673314595547` are the *same* binary64, so it was never a tolerance question, only
  two differently-printed numbers defeating a human comparison. It fixed the digit anyway,
  which is the right call for a field that exists so a human can compare.
- **Its own `_sample` widening introduced a regression it caught and fixed in `c40e690`:**
  "any iterable" silently accepted a `Mapping` (iterating seeds, giving 0.2545 instead of
  5.5) and a `set` (dropping repeated observations, 1.1776 instead of 0.6286). This is the
  hazard of widening a type gate in a kit about not producing plausible wrong numbers, and
  it is the thing the scoped re-review was told to verify above all else.

**Found by the fix wave, and a gap in my own verification discipline:**
`tools/tests/test_check_vectors.py::test_all_vector_files_match_schema` had been **failing on
this branch since the four Wave 2 suites landed** (`assert 20 == 16`), and was fixed in
`e1dc96c`. Task 1's implementer reported that test failing and I accepted it as the expected
consequence of stamping suite names before their files existed — correctly at the time. What
I never did was re-check it once the suites landed, and no later task's verification list
included `tools/tests`, so a red test rode the branch from Task 1 to the final review. The
lesson for the ledger: an expected failure needs a recorded expiry — the commit at which it
must turn green — or it becomes invisible.

Scoped re-review of the fix wave (opus, 732ddd5..f451c84): **all findings addressed, no new
Critical or Important breakage.** It probed the widened `_sample` gate against 29 input kinds
and confirmed the self-caught `Mapping`/`set` fix is the right shape (`Mapping` catches
`dict` and `dict_keys` since a `KeysView` is a `Set`; `.values()` stays accepted because a
`ValuesView` is not). It audited every error class by loading them rather than reading the
diff, and confirmed every raise site's code is preserved. It also caught that the fix wave's
own `sources.Request` audit was one field short — `url` accepts `bytes` too, not only `str` —
while agreeing the lossless-decode conclusion stands.

The re-review found five new Minor issues in the fix diff. The protocol allows no second fix
wave, so each is adjudicated here and surfaced to the user rather than fixed:

Ruling 54 — parked: `_sample`'s `list(values)` raises a bare `TypeError` on a 0-d NumPy
array where 732ddd5 refused it with a coded `StatsError`, because a 0-d array is not a
`Sequence`. Genuinely new and genuinely a regression, but it crashes rather than answering,
the input is implausible, and a two-line `try/except TypeError` closes it. Cost if wrong: an
uncoded exception on an input nobody passes.

Ruling 55 — parked: three places still describe a sample as "any iterable that is not a `str`
or `bytes`", omitting the mapping and set refusals the same wave added —
`test_stats.py:213-214`'s docstring (which now contradicts the test two functions above it),
`bootstrap_ci`'s docstring, and `lab.stats.mdx:155`. Prose contradicting code in the module
whose subject is numeric honesty, and the docstring is the one an IDE shows. It misleads
toward a refusal, not toward a wrong number, which is why it is parked rather than fixed.
Cost if wrong: a caller passes a dict, is refused, and the docstring told them otherwise.

Ruling 56 — parked: the *g*-approximation error figures in `stats.py:18-19` and
`lab.stats.mdx:181-183` are loose in the conservative direction, and the n=50 figure
("0.01%") is seven times the 0.0014% the fix wave's own report measured. Hedged by "about",
so not misleading, but a stated error figure disagreeing with the author's own measurement is
a wart in this module in particular. Cost if wrong: two numbers in prose.

Ruling 57 — parked: `bootstrap_ci` would surface an uncoded `ValidationError` from
`Interval`'s new `low <= high` validator if scipy ever returned inverted BCa bounds, where
the adjacent non-finite backstop raises a coded `StatsError`. Unreachable with scipy's
current percentile ordering; the two guards are merely asymmetric. Cost if wrong: an uncoded
exception on an unreachable path.

Ruling 58 — accepted as a recorded decision, not a gap: the written convention is per module,
so a caller handling "this dataset input is unusable" across `parse_manifest` and
`release_as_of` still needs `except (ManifestError, TemporalError)`, since the two carry
different builtin bases. `lab.data.mdx` states this deliberately. The package-level question
is real but larger than this branch, and `lab.record`'s base-with-no-subclass shape is the one
spine module the new convention does not quite describe. Cost if wrong: the package-level
convention is settled in a later wave instead of this one.

One behaviour change a consumer could feel, verified to have no consumer: `except
LookupError` no longer catches `lab.sources`'s offline miss, because `SourceError` is now a
`ValueError`. The re-reviewer grepped every `except` in the package and found nothing
catching `SourceError`, `TemporalError`, or a base that used to cover them; the example gate
does not touch `lab.sources`; and the distribution is unpublished.

Task 6 dispatched (sonnet), BASE 17d57c8. Reported DONE_WITH_CONCERNS at 1ffadea: 566
passed, 99% coverage, spine 521 passed, mypy clean. All four concerns accepted without a
round, so it went straight to review.

Ruling 32 (Task 6 concern 1, accepted as the implementer decided it): **`CorruptSourceError
(ValueError)` carrying `HEPH-LAB-412` stays.** I had invited this decision in the dispatch
rather than prescribing it, and the reasoning is right on both halves: `spec/errors.yaml`
routes "the artefact exists but says the wrong thing" to 412, and declining to reuse
`lab.data`'s `ManifestError` keeps `lab.sources` from importing a module it has nothing else
to do with. It invents no code. Refusing a corrupted body online as well as offline — no
silent refetch — is the right call too: a cache that quietly heals itself cannot be audited.
The hierarchy question (two unrelated classes here, one subclassing the other in
`manifest.py`, the reverse in `releases.py`) belongs to the package-wide item already
deferred to the final review, not to this task.

Task 6 concerns 2–4 accepted as recorded: `frozen()` scoped to the cache's own
`upstream_version` is coherent because the cache is constructed with exactly one; the pinned
key literal was hand-derived with `shasum` over the JCS text (rule 2 respected); and the
documented limits — no eviction, no locking between writers, and a coordinated rewrite of
body and sidecar being undetectable — are honest rather than fixable. The last one is
inherent: without an external root of trust, a self-consistent forgery cannot be detected,
and saying so in the docstring is the correct answer.

Carried to Task 5's dispatch (re-reviewer's out-of-scope observation, not a Task 2 defect):
`verify_manifest`'s path validation is lexical, so a symlink inside `root` pointing outside
it is not caught. Task 5's `pull` writes files that arrived from a remote, so it is the
task that has to decide whether to resolve symlinks before verifying.

Ruling 14: `extras.py` becomes `_extras.py` and the `lab.extras` row comes out of
`spec/modules.yaml`. The implementer added the row because `check_modules.py` demanded one,
which was the right reading of the checker but the wrong fix: `lab.extras` is not one of
the design's seventeen modules, it has no spec section, no docs page and no maturity story,
and a row claims it is a shipped capability of the kit in the ledger the docs site renders.
`check_modules.py` skips names beginning with `_` precisely for things that sit where
modules live without being modules, which is what an import guard is. Later tasks import
`require` from `hephkit.lab._extras`; their dispatches carry the path. Cost if wrong: a
rename back and one row.
