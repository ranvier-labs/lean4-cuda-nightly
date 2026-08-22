# Lean CUDA nightlies

This repository is the distribution boundary for nightly binary builds of the experimental Lean
CUDA toolchain. The compiler is built in a separate private repository; this repository contains
only release metadata, a small product site and compiler guide, installation instructions, and
the tools that validate those surfaces. This repository is public so its metadata and future
GitHub Release assets are anonymously accessible; publishing a nightly remains an explicit step.

The site may report a candidate build in progress. Downloads appear only after both required
architectures pass and an immutable release record is published.

## Distribution model

- Each nightly is an immutable GitHub prerelease named `nightly-YYYY-MM-DD`, with `-revN` used
  only when the same UTC date must be rebuilt.
- Linux x86_64 and Linux AArch64 toolchains are published together or not at all.
- Large archives live in GitHub Releases. Git and GitHub Pages carry only JSON, documentation,
  and static assets.
- The private source commit is disclosed as a provenance identifier, but is not pushed here.
- Installed private Lean sources are excluded. Public CUDA SDK headers remain in the toolchain
  because downstream `nvcc` compilation requires them.
- Nightlies pass the dual-architecture build, extracted-package smoke test, and full Lean test
  suite. H100 validation is a separate promotion gate and is never implied by the nightly label.

The architecture and privacy boundary are described in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The release handoff is documented in
[`docs/PUBLISHING.md`](docs/PUBLISHING.md).

## Local checks

The tooling uses only Python's standard library.

```bash
make check
make site
python3 -m http.server --directory _site 8000
```

`make check` validates every release record, verifies the agent-facing static files, builds the
site, and runs the unit tests. The generated `_site/` directory is intentionally untracked.

## Repository layout

- `releases/` — one immutable JSON record per published nightly;
- `status/` — the mutable, informational state of the current build candidate;
- `schema/` — the public JSON contract;
- `site/` — static website and agent-readable instructions;
- `scripts/release_tool.py` — semantic validator, source-policy gate, and site builder;
- `tests/` — contract and generation regression tests;
- `.github/workflows/` — validation and GitHub Pages deployment.

Contributions and commit messages follow the Lean 4 convention in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Installing a published nightly

Once the first nightly exists, projects will be able to pin it in `lean-toolchain`:

```text
ranvier-labs/lean4-cuda-nightly:nightly-YYYY-MM-DD
```

Agents should resolve the exact release through `releases/v1/latest.json`, verify its immutable
record and SHA-256 values, and pin the resulting release ID instead of retaining a floating
`latest` reference. See [`site/agent-install.md`](site/agent-install.md).

## License

Apache 2.0. Binary releases also carry the notices and licenses installed by their Lean toolchain
build.
