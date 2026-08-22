# Nightly release contract

Every file in `releases/*.json` conforms to `schema/release-v1.schema.json` and passes the stricter
semantic checks in `scripts/release_tool.py`.

## Identity

- `id` is `nightly-YYYY-MM-DD` or a same-day `nightly-YYYY-MM-DD-revN` retry.
- `version` is embedded in the installed Lean toolchain and includes the UTC date, optional
  revision, and a short prefix of the private source commit.
- `source.commit` is the full private source commit ID. It is provenance, not a public fetch URL.

## Acceptance

A record must describe exactly two artifacts: Linux x86_64 and Linux AArch64. Both must have:

- immutable GitHub Release URLs;
- archive and deterministic-manifest SHA-256 values and byte sizes;
- architecture-correct SASS targets and the declared PTX fallback;
- zero full-suite failures and a passed extracted-package smoke test.

The release-level dual-architecture gate must be `passed`. `h100` may be `not-run` for a nightly;
when it is not passed, `performanceClaims` must be false.

## Content policy

`contentPolicy.privateLeanSources` is `excluded`. Before upload, both archive manifests must pass:

```bash
python3 scripts/release_tool.py verify-manifest path/to/archive.manifest.json
```

The gate rejects absolute paths, traversal, duplicate entries, inconsistent file counts, and any
installed `.lean` file below `src/lean/`. Public CUDA SDK headers are intentionally allowed and
declared through `contentPolicy.sdkHeaders`.

Create a manifest from an installed tree with:

```bash
python3 scripts/release_tool.py build-manifest TOOLCHAIN_ROOT \
  --output lean-VERSION-PLATFORM.manifest.json
```

Entries are ordered by relative POSIX path. Regular files are hashed by contents; symlinks are
recorded without traversal and hash their link-target bytes. The output must be outside the
installed tree so it cannot accidentally include itself.

## Mutability

Release records and assets are immutable. The generated `latest.json` pointer is rebuilt from the
newest accepted immutable record. The separate `status/v1/nightly.json` surface is mutable and
informational: `running` or `failed` never makes a candidate installable. Only a matching immutable
release record grants acceptance. A corrected build receives `-revN`; no file is silently replaced.
