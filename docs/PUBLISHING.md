# Publishing a nightly

The private build workflow and this companion repository communicate through verified
release assets and one small JSON record. Do not copy the private Git history into this repository.

## One-time setup

1. Keep `ranvier-labs/lean4-cuda-nightly` private until its distribution boundary and history pass
   the public-release audit.
2. When the organization plan and desired visibility permit it, enable GitHub Pages with GitHub
   Actions as its source.
3. Set the repository Actions variable `PUBLISH_PAGES=true`. Until then, push-triggered Pages jobs
   intentionally skip; a manual dispatch remains available after Pages has been configured.
4. Install a GitHub App on the companion repository with `Contents: read and write`. Store its app
   ID and private key only in the private build repository, as `CUDA_NIGHTLY_APP_ID` and
   `CUDA_NIGHTLY_APP_PRIVATE_KEY`.
5. Keep the ordinary private workflow `GITHUB_TOKEN` read-only; it cannot and should not publish
   across repositories.
6. Register one Linux `ARM64` self-hosted runner on the private build repository with the
   `cuda-13` label, CUDA 13, CMake, Make, Python, and zstd. The x86_64 package gate runs on a
   GitHub-hosted Ubuntu 24.04 runner and installs NVIDIA's CUDA 13 compiler packages itself.

## Native Lean release path

The CUDA workflow deliberately uses the same release mechanism as Lean itself: configure the
canonical build tree with an install parent and platform suffix, build it, invoke the stage
install target, and compress that installed directory with tar and zstd.

```bash
cmake --preset release -B build/release \
  -DCHECK_OLEAN_VERSION=ON \
  -DINSTALL_LEAN_SOURCES=OFF \
  -DLEAN_CUDA=ON \
  -DLEAN_INSTALL_PREFIX="$PWD" \
  -DLEAN_INSTALL_SUFFIX=-linux_aarch64 \
  -DLEAN_SPECIAL_VERSION_DESC=cuda-nightly.YYYYMMDD.gCOMMIT
make -j"$(nproc)" -C build/release
make -C build/release/stage1 install
dir=$(echo lean-*-linux_aarch64)
tar cf - "$dir" | zstd -T0 --no-progress -19 -o "$dir.tar.zst"
```

`INSTALL_LEAN_SOURCES=OFF` is the sole installed-layout exception. The ordinary Lean default
remains `ON`, while CUDA distributions retain compiled `.olean`/`.ilean` modules, runtime
libraries, public headers, licenses, and the normal command-line tools.

## Private build handoff

1. Derive `nightly-YYYY-MM-DD`, using `-revN` only for a same-day retry, and configure Lean with
   the corresponding `cuda-nightly.<date>[.revN].g<short-commit>` version.
2. Build Linux x86_64 and AArch64 from the same immutable private source commit.
3. Check out the pinned public LeanTest fixtures and run the full Lean test suite against the
   `stage1` build on both architectures before allocating space for an installed distribution.
4. Install through Lean's native stage install target with `INSTALL_LEAN_SOURCES=OFF`. Do not
   install private `src/lean/**/*.lean` files.
5. Run installed-tree validation and the extracted Lake CUDA smoke on both architectures. The
   GitHub-hosted x86_64 job verifies compilation, device linking, native
   linking, packaging, and source privacy without claiming GPU execution; tests that require an
   attached GPU must report skips. The ARM64 GB10 job is the live `sm_121` execution gate.
6. Generate deterministic manifests with `release_tool.py build-manifest`, then run
   `verify-manifest` as the privacy gate on both manifests. Generate checksum sidecars for both
   standard Lean archives.
7. After both architecture jobs pass, create the companion prerelease and upload the two archives,
   sidecars, and manifests. Keep temporary Actions-artifact retention to one day after handoff.
8. Generate `releases/<release-id>.json` with `release_tool.py build-record` from those published
   assets, run `make check`, and push it. Pages deployment then updates the release index and
   latest pointer. The private compiler workflow performs this metadata commit after the GitHub
   Release exists so agents never observe a `latest` pointer with missing URLs.

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

GitHub's automatic "Source code" links for the release contain this source-free companion
repository only. They never contain or point a tag at the private compiler repository.

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

## Source-repository workflow

The private compiler repository owns `.github/workflows/cuda-nightly.yml`. It derives an immutable
nightly identity, runs the canonical release build and full test suite on both architectures,
checks the source-free installed tree and an extracted Lake CUDA project, and creates this
repository's prerelease only after the complete dual-architecture matrix passes.

A same-repository pull request carrying the `cuda-package-ci` label runs the credential-free
x86_64 package gate on GitHub-hosted Ubuntu. That gate never checks out this companion repository,
uses publishing credentials, generates release metadata, or publishes a release. It exists so an
actual GitHub x86 build validates each candidate workflow before the scheduled dual-architecture
publication path is enabled.

The workflow uploads standard Lean archives plus SHA-256 sidecars and deterministic manifests, then
commits the verified `releases/<release-id>.json` record. A release is not advertised as `latest`
until that metadata commit lands; the final step preserves the release-before-pointer ordering.

The private compiler repository is `ranvier-labs/lean4-cuda-backend`. Scheduled CI there publishes
CUDA nightlies to this companion repository; it does not publish official `leanprover/lean4`
nightlies.
