# Kernels and launch

Device code is ordinary Lean in `Cuda.DeviceM`. The launch boundary is intentionally
small.

## Inside a kernel

Available on device: control flow, recursive inductives, recursion, closures, native
structures, `Array`, `String`, arbitrary `Nat`/`Int`, and thread-private `ST.Ref`.
The device runtime reimplements the Lean object model on per-block bump arenas. There
is no individual free and no tracing collector on device.

Rejected on device: host `IO`, `Task`, mutexes, and dynamic loading. There are no
implicit CPU fallbacks.

## Launch parameters

Kernel arguments must be explicit scalars, device pointers or slices, `Dim3`, or
address-free POD records (`deriving Cuda.POD`). Device slices become owning
`Cuda.Buffer` values on the host companions.

```lean
structure SaxpyParams where
  a : Float32
  deriving Cuda.POD

def main : IO Unit := do
  -- allocate, copyFrom, then:
  let handle ← saxpy.launch config params xs ys
  handle.waitChecked "saxpy"
```

Prefer the stream-taking companions `kernel.launchOn stream config …`. Plain `launch`
uses the legacy default stream. Streams from `Cuda.Stream.create` are non-blocking
and do not order against default-stream work. A copy on a user stream followed by a
plain `launch` is a data race.

Generated host companions from `@[cuda_kernel]`: `launch`, `launchOn`, `attributes`,
`occupancy`. Persistent workers also get `start` / `startOn`.

## Persistent workers

`@[cuda_persistent]` starts resident block workers that consume a bounded, typed
host-to-device POD queue. Use this for long-lived host-fed work instead of relaunching
a grid for every item. Grid-persistent kernels exist for cooperative whole-grid
residency.

## Build recipe

1. Emit `.c` and `.cu` with `lean --cuda`.
2. Compile the CUDA unit with `nvcc` for the target architecture.
3. Device-link against a runtime object built for that same architecture.
4. Native-link with `leanc` and `libLeanCuda`.

Runnable compact examples live in the companion `lean-cuda-examples` repository:
saxpy, reduce, histogram, async launch, GEMM, a language-feature tour, physical cores,
cluster stencil, and host I/O.
