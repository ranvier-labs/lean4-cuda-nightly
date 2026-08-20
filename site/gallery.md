# Examples

Four GB10 runs. Each kernel is Lean; the still is the device output. Human page: `gallery.html`.

## `mandelbrot`

One cooperative block per SM. Warp workers claim 8×8 tiles from a shared ticket
queue. 1024², 1000 iterations.

```lean
@[cuda_kernel]
def mandelSM (output tileOwner coreTiles coreIters gcursor : Cuda.DevicePtr UInt32) :
    Cuda.DeviceM Unit := do
  let worker ← Cuda.SM.Worker.current warpsPerWorker
  let claims ← Cuda.dynamicShared (α := UInt32) 0
  let disp : Cuda.SM.Dispatch := { cursor := gcursor, claims, limit := numTiles }
  renderLoop disp worker output tileOwner coreTiles coreIters
```

Stills: `gallery/mandelbrot.png`, `gallery/mandelbrot-cores.png`.

## `plume_amr`

Regridding-free quadtree. Fixed slots; refine/coarsen is flag-flipping in one
cooperative megakernel. Shock stretch is the same tree with Godunov + HLLC.

```lean
private def slotOf (level ix iy : UInt32) : UInt32 :=
  levelOffset level + iy * pow2 level + ix

@[cuda_kernel]
def plumeDynMega (...) : Cuda.DeviceM Unit :=
  plumeStep ... 0
```

Stills: `gallery/plume.png`, `gallery/shock.png`.

## `persistent_training`

2048 SGD steps of a 16-class linear classifier in one persistent launch.
64-step mean loss 2.68 → 0.17.

```lean
@[cuda_persistent]
def trainStep (item : TrainItem) (config : LinearClassifier.Config)
    ... : Cuda.DeviceM Unit := do
  let shared : Cuda.DevicePtr UInt8 ← Cuda.dynamicShared (α := UInt8)
  LinearClassifier.runItem16 config state item.sample shared
```

Still: `gallery/loss.svg`.

## `stealth_shape_optimization`

Discrete-form Helmholtz inverse design. One CTA per candidate. A 2D silhouette
proxy, not a 3D aircraft.

```lean
@[cuda_kernel]
def optimizeStealth (...) : Cuda.DeviceM Unit := do
  let candidate := (← Cuda.blockIdxX).toUSize
  let thread ← Cuda.Concurrent.Thread.blockIndex
  emptyMaterialFrom electricCandidate thread.rank thread.count edgeBins.size
```

Still: `gallery/stealth.svg`.
