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
