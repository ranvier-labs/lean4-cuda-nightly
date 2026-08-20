# Lean CUDA

Experimental Lean 4 compiler backend. Compiles ordinary Lean declarations to CUDA
device code. Not an upstream Lean release. Alpha: attributes, launch ABI, and build
recipe will change.

## One-sentence model

Mark a Lean definition `@[cuda_kernel]`. Lean emits CUDA C++ and typed host
companions (`launch`, `attributes`, `occupancy`). Lean owns the kernel. C++ is only
instruction-sized shims (TMA, WGMMA, `mbarrier`, `stmatrix`, register redistribution).

## Example

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

SAXPY from the companion example repository. Host `Float32` arithmetic is the bit-exact
oracle for that example.

## Facts

- Lean owns control flow, tiling, synchronization, and ownership.
- Launch parameters: scalars, device pointers/slices, `Dim3`, or address-free POD records.
- Host `IO`, `Task`, mutexes, and dynamic loading are rejected on device.
- Nightlies: Linux x86_64 and Linux AArch64, source-free installed trees.
- A nightly does not imply an H100 performance claim.
- Agents: start at `agent.md` and `llms.txt`. Humans: `index.html`.
