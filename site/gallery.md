# Examples

Compact kernels and a few application workloads, all written in Lean. Stills below are
device outputs from GB10 runs. Human page: `gallery.html`.

## Simulation results

- `gallery/mandelbrot.png` — `mandelbrot`. One cooperative block per SM; warp workers
  claim 8×8 tiles from a shared ticket queue. 1024², 1000 iterations.
- `gallery/mandelbrot-cores.png` — per-tile ownership; color is the physical SM that
  claimed the tile.
- `gallery/plume.png` — `plume_amr`. Incompressible buoyant plume. The AMR tree
  re-refines in-kernel; slots recycle.
- `gallery/shock.png` — compressible Euler, Godunov + HLLC, Löhner indicator. Same
  megakernel as the plume.
- `gallery/loss.svg` — `persistent_training`. 2048 SGD steps of a 16-class linear
  classifier in one persistent launch. 64-step mean loss 2.68 → 0.17.
- `gallery/stealth.svg` — `stealth_shape_optimization`. Discrete-form Helmholtz inverse
  design, one CTA per candidate. A 2D silhouette proxy, not a 3D aircraft or certified RCS.

## Ready

| id |  |
| --- | --- |
| saxpy | Typed launch, device buffers, bit-exact host oracle |
| reduce | Dynamic shared memory, convergent block reduction |
| histogram | Global atomics; Philox RNG replayed on the host |
| async_launch | Streams, events, `launchOn`, kernel handles |
| gemm | Shared-memory tiled SGEMM, typed static tensor views |
| features | Inductives, closures, arrays, strings, `ST.Ref` on device |
| physical_cores | `Cuda.SM`, Hopper clusters, DSM, mailboxes |
| cluster_stencil | Jacobi stencil, interior halo through distributed shared memory |
| host_io | Mapped typed queues and owned bulk regions |
| mandelbrot | Ticket-scheduled SM workers, ownership map |
| plume_amr | Regridding-free tree AMR; plume and HLLC shock |
| persistent_training | Full SGD loop in one persistent launch |
| mixture_of_kittens | Typed shared-plus-routed SwiGLU, eight gradient groups |
| stealth_shape_optimization | DEC Maxwell / Helmholtz reciprocal adjoint |

## Planned

hybrid_mpc, branchingflows_molecule, transformer_training, persistent_llama,
sparse_event_kda, streaming_moe, torchlean_certified_inference, r1_vm.

The catalog contract is `gallery.tsv` in the companion example repository.
