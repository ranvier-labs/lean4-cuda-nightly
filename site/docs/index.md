# The Lean CUDA extension

How marked Lean declarations become CUDA device code, what you can write inside a
kernel, and what the alpha still refuses.

Sibling pages: [kernels](kernels.md), [runtime](runtime.md). Agent briefing: [../agent.md](../agent.md).

## Compile path

A staged Lean build configured with `LEAN_CUDA=ON` advertises `[CUDA]` from
`lean --features`. Marked declarations go through LCNF. A CUDA emitter writes a
`.cu` translation unit next to the usual C output:

```text
lean --root=. -c Kernel.c --cuda=Kernel.cu \
  -Dcompiler.postponeCompile=false Kernel.lean
```

`nvcc` compiles that unit for the chosen `-arch`. Lake packages use
`Lake.buildLeanCudaO` and `Lake.buildCudaDeviceLink`. The device-link step compiles
the installed device runtime for the package architecture, so an `sm_90a` package
does not pick up an `sm_121` runtime object just because Lean itself was built on a
Blackwell machine.

Whole-program mode (`codeMode := .wholeProgram`) compiles the generated program and
runtime as one translation unit with `-rdc=false`. Hopper register budgets require
that mode: CUDA 13 `ptxas` otherwise discards `setmaxnreg` (warning C7504).

## Attributes

| Attribute | Meaning |
| --- | --- |
| `@[cuda_kernel]` | Device entrypoint plus typed host launch companions |
| `@[cuda_device]` | Helper used from device code; no host launch wrapper |
| `@[cuda_persistent]` | Resident block workers behind a bounded host-to-device POD queue |
| `@[cuda_grid_persistent]` | Grid-wide persistent workers |
| `@[cuda_launch_bounds]` / `@[cuda_max_registers]` | Occupancy and register file |

## Requirements

- A CUDA-enabled Lean toolchain (nightly, or a source build with `LEAN_CUDA=ON`)
- CUDA 13, `nvcc` on `PATH`
- An NVIDIA GPU for execution. Development target: GB10 (`sm_121`). Hopper-only
  features compile for `sm_90a` and execute on H100-class hardware.

## What this is not

- Not upstream Lean
- Not a general autograd transform. Discrete-form adjoints and custom VJPs are
  explicit library code, not a tape
- GPU-less test runs can skip execution and still look green — read the test output
