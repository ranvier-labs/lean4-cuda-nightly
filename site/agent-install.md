# Agent procedure: install a Lean CUDA nightly

Use this procedure noninteractively and fail closed. Read `agent.md` first for
identity and API bounds. This file is only the install decision procedure.

## 1. Resolve

Fetch `releases/v1/latest.json` relative to the website root. If `release` is null, report that no
public nightly exists and stop. Otherwise resolve `release.metadataUrl` relative to the latest
pointer URL, fetch it, and require:

- `schema == "lean.cuda.release/v1"`;
- `channel == "nightly"`;
- `gates.dualArchitectureCI == "passed"`;
- `contentPolicy.privateLeanSources == "excluded"`.

Record the immutable release `id`; do not retain `latest` as the selected version.

## 2. Select the native artifact

Run `uname -s` and `uname -m`. Require Linux and map only:

- `x86_64` → artifact architecture `x86_64`;
- `aarch64` or `arm64` → artifact architecture `aarch64`.

Reject every other host. Select exactly one artifact with matching `hostSystem` and
`architecture`.

## 3. Install and verify

Use the selected artifact's immutable `url` and expected `sha256`:

```bash
archive_name='value from artifact.name'
archive_url='value from artifact.url'
expected_sha256='value from artifact.sha256'
install_root='new version-specific directory'
curl -fL -o "$archive_name" "$archive_url"
printf '%s  %s\n' "$expected_sha256" "$archive_name" | sha256sum -c -
mkdir "$install_root"
tar --zstd -xf "$archive_name" -C "$install_root" --strip-components=1
"$install_root/bin/lean" --version
"$install_root/bin/lean" --features
```

Require `lean --features` to contain `CUDA`. Optionally register the verified tree under a local
name with `elan toolchain link <local-name> <new-version-directory>`.

For the convenient self-updating path, `elan toolchain install <installation.elanToolchain>` is
compatible with the release assets. Current elan does not compare a custom release asset with this
channel's checksum sidecar, so do not report that path as independently checksum-verified. Write
the exact remote identity to a project's `lean-toolchain` only with user authorization to modify
that project. Never overwrite an existing toolchain directory and never execute an unverified
direct download.

## 4. Report the boundary

Report the release ID, source commit identifier, artifact architecture and SHA-256, CUDA toolkit
requirement, embedded SASS/PTX targets, and H100 gate state. Do not infer a performance result when
`gates.performanceClaims` is false.
