# Publishing a nightly

The private build workflow and this companion repository communicate through verified
release assets and one small JSON record. Do not copy the private Git history into this repository.

## One-time setup

1. Keep `ranvier-labs/lean4-cuda-nightly` private while staging the channel.
2. Enable GitHub Pages using GitHub Actions as the source when the organization plan and desired
   visibility permit it.
3. Install a GitHub App on the companion repository with only the repository permissions needed to
   create releases and push release records. Store its credentials only in the private build
   repository.
4. Keep the ordinary private workflow `GITHUB_TOKEN` read-only; it cannot and should not publish
   across repositories.

## Private build handoff

1. Derive `nightly-YYYY-MM-DD`, using `-revN` only for a same-day retry, and configure Lean with
   the corresponding `cuda-nightly.<date>[.revN].g<short-commit>` version.
2. Build Linux x86_64 and AArch64 from the same immutable private source commit.
3. Install with the compiled-toolchain packaging profile. Do not install private
   `src/lean/**/*.lean` files.
4. Run installed-tree validation, extracted Lake CUDA smoke, and the full Lean test suite on both
   architectures.
5. Generate deterministic manifests and checksum sidecars. Run this repository's
   `verify-manifest` privacy gate on both manifests.
6. Create a draft prerelease in the distribution repository and upload the two archives,
   sidecars, and manifests. Set temporary Actions-artifact retention to one day after handoff.
7. Verify every uploaded asset's size and digest, then publish the GitHub prerelease.
8. Add `releases/<release-id>.json`, run `make check`, and push it. Pages deployment then updates
   the release index and latest pointer.

Publishing the GitHub release before the metadata commit creates a safe short interval in which an
asset exists but is not advertised. Reversing the order could make agents observe broken URLs.

## Elan compatibility

Use the standard Lean archive names:

```text
lean-<version>-linux.tar.zst
lean-<version>-linux_aarch64.tar.zst
```

Attach them to the companion release tag. Consumers with repository access can then pin:

```text
ranvier-labs/lean4-cuda-nightly:<release-id>
```

The tag may target an ordinary companion metadata commit. Elan consumes the release asset; the
tag does not need to contain the private compiler source.

GitHub release assets in a private repository are not anonymous downloads. Before an external
nightly launch, either make this source-free companion repository public or mirror the release
assets and generated site to a public distribution host. This visibility change does not expose
the separate compiler repository.

Elan currently discovers custom-repository assets by the platform suffix (`linux.` or
`linux_aarch64.`), so the internal Lean version may be more specific than the release tag. Its
custom-release download path does not consume the `.sha256` sidecar; the agent guide therefore
uses direct download plus explicit SHA-256 verification as the strict path. See elan's
[`manifestation.rs`](https://github.com/leanprover/elan/blob/master/src/elan-dist/src/manifestation.rs)
and [`download.rs`](https://github.com/leanprover/elan/blob/master/src/elan-dist/src/download.rs).

## Source-repository changes still required

The current CUDA release workflow must gain four narrowly scoped changes before its first nightly:

1. a scheduled nightly/version derivation path;
2. a compiled-toolchain install profile that omits private Lean sources;
3. source-independent installed archive verification;
4. a cross-repository publish job that runs only after both architecture jobs pass.

Those changes belong in the private source repository, not here.
