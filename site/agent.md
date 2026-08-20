# Agent briefing: Lean CUDA

Read this file, then `llms.txt`. Prefer the markdown pages over HTML. HTML is a human
skin; it is not the source of facts.

Fail closed. If a required fact is missing, say so and stop. Do not invent APIs,
performance numbers, or upstream-Lean status.

## Identity

Lean CUDA is an **experimental Lean 4 compiler backend**. It lowers ordinary Lean
declarations marked `@[cuda_kernel]`, `@[cuda_device]`, `@[cuda_persistent]`, or
`@[cuda_grid_persistent]` to CUDA C++ device code.

It is **not** upstream Lean. It is **not** “call a C++ kernel from Lean.” Lean owns
control flow, tiling, coordinate arithmetic, synchronization policy, and resource
ownership. C++ is limited to force-inlined, instruction-sized shims for operations
CUDA C++ cannot express directly: TMA, WGMMA, `mbarrier`, `stmatrix`, and register
redistribution.

The backend is **alpha**. Attributes, the launch ABI, and the Lake recipe will change.

This repository distributes **source-free nightly binaries**. The compiler Git history
is private. Installed trees omit `src/lean/**/*.lean`. Public CUDA SDK headers remain
because consumer `nvcc` still needs them.

## Routing

| Task | Read |
| --- | --- |
| What this is | `about.md` |
| Compile path, attributes, requirements | `docs/index.md` |
| `DeviceM`, launch ABI, persistent workers | `docs/kernels.md` |
| Concurrency, SM/cluster, alpha limits | `docs/runtime.md` |
| Examples and simulation stills | `gallery.md` |
| Human install notes | `install.md` |
| Noninteractive install | `agent-install.md` |
| Nightly pointer | `releases/v1/latest.json` |
| Release contract | `schema/release-v1.schema.json` |

If `releases/v1/latest.json` has `"release": null`, no public nightly exists. Report that
and stop. Do not tell the user to install `latest`.

## How to describe a kernel

A `@[cuda_kernel]` definition of type `Cuda.DeviceM Unit` emits:

1. a CUDA C++ translation unit with the device function and a `__global__` wrapper;
2. typed host companions from the signature: `kernel.launch`, `kernel.launchOn`,
   `kernel.attributes`, `kernel.occupancy`.

Launch parameters must be explicit scalars, device pointers/slices, `Dim3`, or
address-free POD records (`deriving Cuda.POD`). Host `IO`, `Task`, mutexes, and
dynamic loading are rejected on device. There are no implicit CPU fallbacks.

Minimal shape:

```lean
@[cuda_kernel]
def saxpy (params : SaxpyParams) (xs ys : Cuda.DeviceSlice Float32) :
    Cuda.DeviceM Unit := do
  let i := (← Cuda.blockIdxX) * (← Cuda.blockDimX) + (← Cuda.threadIdxX)
  if i.toUSize < xs.size then
    let x ← Cuda.loadFloat32 xs.ptr i.toUSize
    let y ← Cuda.loadFloat32 ys.ptr i.toUSize
    Cuda.storeFloat32 ys.ptr i.toUSize (params.a * x + y)
```

Prefer `kernel.launchOn stream config …`. Plain `launch` uses the legacy default
stream and does not order against user-created non-blocking streams.

## How to compile

```text
lean --root=. -c Kernel.c --cuda=Kernel.cu \
  -Dcompiler.postponeCompile=false Kernel.lean
```

Then `nvcc` for the chosen `-arch`, device-link a runtime object built for that same
architecture, native-link with `leanc` / `libLeanCuda`. Lake:
`Lake.buildLeanCudaO` and `Lake.buildCudaDeviceLink`.

Hopper `setmaxnreg` register budgets require `{ codeMode := .wholeProgram }`. Relocatable
device code drops the instruction (CUDA 13 ptxas C7504).

Require `lean --features` to contain `CUDA`. Require CUDA 13 `nvcc`.

## Hardware

- Development execution: NVIDIA GB10, `sm_121`.
- Hopper-only shims (WGMMA, TMA tensor maps, `setmaxnreg`) compile for `sm_90a` and
  execute on H100-class hardware.
- Off-architecture use of gated shims is a **compile-time** failure, not a device `trap`.
- GPU-less tests may skip execution and still exit 0. Inspect the log; do not report a
  skip as a passing device run.

## Nightlies

Supported hosts: Linux `x86_64` and Linux `aarch64` only. Both architectures are
published together or not at all.

Follow `agent-install.md` to install. Pin a release ID. Never write a floating
`latest` into a project `lean-toolchain` without user authorization. Current elan
downloads custom GitHub Release assets over HTTPS but does **not** check this
channel's SHA-256 sidecar; do not call that path checksum-verified.

## Things you must not say

- “This is official Lean” / “this is in Lean 4 stable.”
- “It autograds CUDA kernels.” Discrete-form adjoints are explicit library VJPs, not a tape.
- “Install `ranvier-labs/lean4-cuda-nightly:latest` for reproducibility.”
- Any API, attribute, or Lake flag not named in these markdown pages.

## License

Apache 2.0. Binary releases also carry the notices installed with the toolchain.
