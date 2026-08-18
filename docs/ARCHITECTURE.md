# Distribution architecture

## Boundary

The private build repository owns the compiler source, CUDA backend implementation, build
workflow, and release-candidate evidence. This companion repository owns only the binary
distribution surface. It remains private during staging and can later be made public or mirrored
to a public host without exposing the compiler repository:

```text
private Lean CUDA repository
        |
        | dual-architecture build and validation
        v
public GitHub prerelease assets
        |
        +-- lean-<version>-linux.tar.zst
        +-- lean-<version>-linux_aarch64.tar.zst
        +-- checksum sidecars and deterministic manifests
        |
        v
public immutable release JSON --> latest/index JSON --> Pages + agents
```

The distribution release tag points at this companion repository's metadata history. It never points at
or imports the private source Git object. GitHub's automatically generated source archives
therefore contain only this companion repository, not the compiler source.

## Toolchain layers

Lean's compiler and compiled library remain one version-locked toolchain. They are logically
separate inside the archive but are published together because `.olean` contents, compiler
extensions, the runtime ABI, and native initializers must match exactly.

The installed tree contains:

1. `bin/`: `lean`, `leanc`, `lake`, and supporting tools;
2. `lib/lean/`: compiled `.olean`/`.ilean` modules, native libraries, and CUDA device objects;
3. `include/lean/`: public host and CUDA SDK headers;
4. licenses and notices.

It does not contain private `src/lean/**/*.lean` files. Omitting those sources removes
go-to-definition into the private toolchain implementation, but does not prevent imports from
loading the compiled `.olean` modules. Exact build provenance lives in the immutable release
record and archive manifest rather than in an extra nonstandard installed file.

## CUDA SDK exception

The current Lake integration invokes `nvcc` on generated CUDA and compiles the installed device
runtime for the consumer-selected architecture. Consequently the required `.h` and `.cuh` SDK
headers are distributable inputs, not private compiler source. A future fully opaque runtime
would require precompiled runtime objects for every supported architecture and would constrain
whole-program mode; that is not part of the first nightly channel.

## Channels

- **nightly:** automatic dual-architecture compiler, package, smoke, and full-suite gate;
  no H100 performance implication;
- **alpha:** manual promotion of an immutable nightly after any additional hardware and release
  gates required by the alpha policy.

A nightly is useful for early adopters and agents without weakening the stronger alpha claim.

## Agent interface

HTML is for discovery, not automation. The stable automation surface is:

- `llms.txt` — concise capability and routing map;
- `agent-install.md` — noninteractive decision procedure;
- `releases/v1/latest.json` — nullable pointer to the newest accepted nightly;
- `releases/v1/index.json` — ordered release summaries;
- `releases/v1/<release-id>.json` — immutable complete release record.
- `schema/release-v1.schema.json` — release record structure.

Agents must pin a release ID after resolving `latest` and verify the selected archive's SHA-256.
