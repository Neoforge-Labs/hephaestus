# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
vulnerability reporting instead: on the repository page, open the **Security**
tab and choose **Report a vulnerability**. The report is visible only to the
maintainers until we publish an advisory.

Include what you found, how to reproduce it (a failing conformance vector is
ideal), and which module and version it affects.

We will acknowledge a report within 5 days and tell you what we plan to do
about it within 14 days. If a fix is warranted we will credit you in the
advisory unless you ask us not to.

## Advisories in our dependency tree

Dependabot watches the lockfiles. Where an advisory names a fixed version we
take it. Where it names none, the assessment lives here, so the reason an alert
is closed is in the repository and reviewable, rather than in a dismissal
comment nobody reads again.

### `diskcache`: GHSA-w8v5-vhqr-4h9v, CVE-2025-69872, unsafe pickle deserialization

**Where it comes from.** `python/hephkit-lab/uv.lock`, transitively and only
under the `data` extra: `dvc` to `dvc-data` to `diskcache`. No code in this
repository imports it, and a spine-only install ([ADR
0023](docs/adr/0023-hephkit-lab-ships-separately.md)) does not contain it at all.

**Why there is nothing to upgrade to.** The advisory covers every released
version (`<= 5.6.3`), 5.6.3 is the latest release on PyPI, and GitHub reports no
first patched version. A pin cannot resolve it, and `dvc-data` requires it
unconditionally, so the dependency cannot be dropped without dropping DVC.

**Why it is tolerable here.** The attack needs an attacker who can write to a
cache directory that the victim process then reads. The only DVC repository our
code creates is the throwaway one in `hephkit.lab.data.snapshots._scratch_repo`:
a fresh `tempfile.TemporaryDirectory` (mode `0700`, owner-only), initialised
with `Repo.init(..., no_scm=True)` on every call, holding its own cache, and
removed when the call returns. The diskcache instance our code causes to exist
is therefore created, read and destroyed inside a private directory no other
user can write to, inside one call. A developer who runs `dvc` by hand in their
own checkout carries the upstream risk that every DVC user carries; we do not
add to it.

**What would change this.** A `diskcache` release that drops pickle or fixes the
deserialization (take it), a `dvc-data` that stops requiring it (take that), or
any code here that reads a DVC cache it did not create in a directory it does
not own, at which point this assessment is void and the alert should be reopened.

## Supported versions

| Version | Supported |
| --- | --- |
| `0.x`, latest only | yes |
| anything older | no |

## What to expect from the code today

Every module in Hephaestus is currently labelled `experimental` (see
[ADR 0015](docs/adr/0015-maturity-levels.md)). Nothing here is yet fit for a
production money path, and the rules in [`CLAUDE.md`](CLAUDE.md) say so too:
nothing below `stable` may sit in one. Reports against `experimental` modules
are still welcome, and a flaw in money, ledger, audit, outbox, idempotency or
auth handling is exactly the kind of thing we want to hear about before a
module is promoted.
