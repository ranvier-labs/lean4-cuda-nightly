# Install Lean CUDA nightly

Lean CUDA nightlies are experimental Linux toolchains. They are not upstream Lean releases and
may change incompatibly between dates.

No public nightly is available until `releases/v1/latest.json` contains a non-null `release`.

## Requirements

- Linux x86_64 or AArch64;
- `elan` for the preferred installation path;
- CUDA 13 `nvcc` to compile CUDA programs;
- a CUDA-13-compatible NVIDIA driver and supported NVIDIA GPU for execution.

## Convenient: elan

Resolve `releases/v1/latest.json` relative to the website root, follow its immutable metadata
record, and use the exact `installation.elanToolchain` value:

```bash
elan toolchain install ranvier-labs/lean4-cuda-nightly:nightly-YYYY-MM-DD
elan run ranvier-labs/lean4-cuda-nightly:nightly-YYYY-MM-DD lean --version
elan run ranvier-labs/lean4-cuda-nightly:nightly-YYYY-MM-DD lean --features
```

For a project, put the same pinned value in `lean-toolchain`. Do not write a floating `latest`
alias into a reproducible project. Current elan selects the correct custom GitHub Release asset
and downloads it over HTTPS, but does not compare it with this channel's checksum sidecar.

## Checksum-verified installation

1. Map `uname -m` to the exact artifact architecture: `x86_64` or `aarch64`.
2. Download the archive and checksum sidecar from the immutable release record.
3. Run `sha256sum -c <archive>.sha256`.
4. Extract with `tar --zstd -xf <archive>`.
5. Set `LEAN_SYSROOT` to the extracted root and prepend its `bin/` to `PATH`.
6. Confirm `lean --features` reports `CUDA`.

The extracted root can also be registered locally with `elan toolchain link <name> <root>`.

Every release record declares its CUDA toolkit version, SASS targets, PTX fallback, test counts,
and hardware-validation boundary.
