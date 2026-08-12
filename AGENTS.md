# Repository instructions

This repository is a distribution boundary, not a compiler source tree.

## Invariants

- Never copy private Lean compiler source, source archives, build logs, credentials, or GitHub
  Actions artifacts into this repository.
- Never commit toolchain archives. GitHub Release assets hold binaries; Git and Pages hold only
  small metadata and documentation.
- A release record is immutable after publication. Correct a bad nightly by publishing a
  `-revN` release and leave the original record intact.
- Both `linux/x86_64` and `linux/aarch64` artifacts must be present and accepted before a record
  can become latest.
- The installed-archive manifest must pass `release_tool.py verify-manifest`; in particular,
  private `src/lean/**/*.lean` files are forbidden. CUDA SDK `.h` and `.cuh` headers are expected.
- A nightly does not carry H100 performance claims unless its record explicitly contains a
  passed H100 gate with durable evidence.
- URLs in release records must be immutable HTTPS GitHub Release asset URLs, never expiring
  GitHub Actions artifact URLs.
- Keep the website derivative of JSON records. Do not hand-edit generated files in `_site/`.

## Validation

Run before handing off changes:

```bash
make check
git diff --check
```

When changing the release contract, update the schema, semantic validator, fixtures,
documentation, `llms.txt`, and tests together.

## Commits and pull requests

Follow Lean 4's commit convention documented in `CONTRIBUTING.md`: use
`<type>: <imperative lowercase subject>` with no trailing period. The accepted types are `feat`,
`fix`, `doc`, `style`, `refactor`, `test`, `chore`, and `perf`. A `feat` or `fix` body begins with
`This PR `, and its pull request carries an appropriate `changelog-*` label.
