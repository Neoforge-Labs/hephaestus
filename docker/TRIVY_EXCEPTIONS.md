# Trivy exceptions — heph-python, heph-node

Scanned with Trivy 0.76.1 on 2026-11-05: `trivy image --severity HIGH,CRITICAL`.

**Gate:** `trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 <image>`
passes (0 findings) for both images. Every finding below is one for which
Debian 12 (bookworm) has **no fixed package yet**, so there is nothing to
update to. The images already run `apt-get upgrade` at build time, so every fix
Debian has published is applied. Trivy's status column is Debian's own:
`affected` (no fix released), `fix_deferred` (Debian has decided to fix later),
`will_not_fix`.

**Standard of evidence:** the reasoning below is role-based (what the package is
for and how these images use it), not exploit analysis.

Reasoning below is about exposure in these images (non-root uid 10001, no
setuid binaries, no shell services, no init system). It is not an independent
exploit analysis; where a claim rests on the package's role rather than the
advisory text, it says so. **Review on every base-image digest bump and delete
an entry as soon as Debian ships a fix.**

Affected images: **P** = heph-python, **N** = heph-node.

| CVE | Sev | Debian status | Packages | Img | Why it is accepted for now |
|---|---|---|---|---|---|
| CVE-2023-45853 | CRITICAL | will_not_fix | zlib1g | P N | Overflow is in `zipOpenNewFileInZip4_6`, part of zlib's contrib *minizip*, which Debian does not build into `libz`. The library the images ship does not contain the vulnerable function. Debian's will_not_fix reflects that. |
| CVE-2026-76844 | HIGH | affected | zlib1g | P N | Title appears mis-attributed in the Trivy DB (it describes `webpack-dev-middleware`, not zlib); not verified upstream. Accepted because no Debian 12 fix is available. |
| CVE-2026-53613 | HIGH | affected | util-linux, mount, bsdutils, libblkid1, libmount1, libsmartcols1, libuuid1, util-linux-extra | P N | TOCTOU in the `mount` program. All setuid/setgid bits are stripped at build and the container user has no `CAP_SYS_ADMIN`, so `mount` cannot perform a privileged mount for it. |
| CVE-2026-78410 | HIGH | affected | (same util-linux set) | P N | Restricted bind mounts not pinning the source. Same reasoning: needs the `mount` program to act with privilege, which the unprivileged user cannot obtain. |
| CVE-2026-53615 | HIGH | affected | (same util-linux set) | P N | Integer overflow in the DOS partition parser (libblkid). Triggers only when probing a crafted disk or image; services here do not probe block devices. |
| CVE-2025-69720 | HIGH | affected | ncurses-base, ncurses-bin, libtinfo6 (P also libncursesw6) | P N | Buffer overflow in ncurses. Used for terminal handling by interactive tools; services do not feed untrusted input to ncurses programs. Rests on package role, not the advisory body. |
| CVE-2026-16742 | HIGH | fix_deferred | libsystemd0, libudev1 | P N | Local privilege escalation in `systemd-homed`. Only the client libraries are installed; there is no systemd, no `systemd-homed`, no init in the container. |
| CVE-2026-41992 | HIGH | fix_deferred | gzip | P N | Information disclosure parsing LZH input. gzip is present only as a Debian base utility; nothing in the images decompresses untrusted LZH data. |
| CVE-2026-54369 | HIGH | fix_deferred | libacl1 | P N | Symlink traversal via libacl functions. Needs a privileged process manipulating ACLs on attacker-influenced paths; the container user is unprivileged. |
| CVE-2026-9538 | HIGH | fix_deferred | perl-base | P N | Denial of service in perl-Archive-Tar. `perl-base` does not ship `Archive::Tar` (checked: no `Tar.pm` on the filesystem), so the vulnerable module is not present. |
| CVE-2025-7458 | CRITICAL | affected | libsqlite3-0 | P | SQLite integer overflow. Present because CPython's `sqlite3` module links it. Hephaestus services use Postgres (CLAUDE.md rule 6); a service that opens untrusted SQLite databases or runs untrusted SQL must re-assess. |
| CVE-2026-11822 | HIGH | fix_deferred | libsqlite3-0 | P | SQLite FTS5 full-text search. Only reachable by an application that uses FTS5 with untrusted data. Same Postgres reasoning. |
| CVE-2026-11824 | HIGH | fix_deferred | libsqlite3-0 | P | SQLite heap overflow. Same as above. |
| CVE-2026-119373 | HIGH | affected | libsqlite3-0 | P | SQLite FTS heap overflow (DoS). Same as above. |

## Fixed by the image build rather than excepted

- `npm` 11.20 bundled `undici` 6.28.0 and `brace-expansion` 5.0.9, with four
  and two fixable HIGH CVEs respectively (CVE-2026-109383, -109869, -19534,
  -87018; CVE-2026-102276, -102278). heph-node is a runtime image, so npm and
  npx are removed. Node's own `undici` (8.12.2) is not affected.
