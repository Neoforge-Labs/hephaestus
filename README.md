# Hephaestus

Hephaestus (`heph`) is NeoForge Labs' full-stack kit: the forge every NeoForge
product and research project is built from. Each project it creates is an
**ingot**. It spans Rust, Go, Python, TypeScript, Terraform, Compose and CI.

Status: Phase 1 (core and local stack) is under construction. Every module is
labelled `experimental`; see [ADR 0015](docs/adr/0015-maturity-levels.md).

| Where | Name |
| --- | --- |
| Site | `hephkit.dev` |
| Repo, CLI | `Neoforge-Labs/hephaestus`, `heph` |
| PyPI | `hephkit` |
| crates.io | `hephkit-core` |
| npm | `@hephkit/*` |
| Go | `github.com/Neoforge-Labs/hephaestus/go` |
| Images | `ghcr.io/neoforge-labs/heph-<runtime>` |

## Where to look

- Site: https://hephkit.dev
- Design: `docs/superpowers/specs/2026-11-04-hephaestus-design.md`
- Decisions: `docs/adr/`
- Contributor rules: `CLAUDE.md`
- Review steps a check cannot enforce: [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Development

Tool versions are pinned in `.prototools` (go, python, uv, node, bun) and
`rust-toolchain.toml` (Rust). Tasks run through moonrepo (`.moon/`).

```
python tools/check_adrs.py
uv run --with pytest pytest tools/tests -v
```

## Licence

MIT. See `LICENSE`.
