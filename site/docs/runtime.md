# Runtime and limits

CUDA’s worker hierarchy is structured, not spawned. Hardware features are gated at
compile time. Alpha restrictions still apply.

## Structured concurrency

`Lean.Cuda.Concurrent` organizes workers that already exist:
`Thread.{blockIndex, gridBlockIndex, gridIndex}`, strided `Warp` / `Block` /
`Grid.forEach`, scope `sync`, and exactly-once `single`. These do not spawn
host-style tasks. Warp and block collectives need convergent participation. Grid
collectives need a cooperative launch.

## Physical cores

- `Cuda.SM` launches one cooperative block per SM and splits it into independently
  synchronized warp-group workers.
- `Cuda.Cluster` treats a static Hopper thread-block cluster as one core, with a
  block worker in each rank and distributed shared memory for halo exchange.
- `Cuda.Mailbox` is a bounded typed POD channel.
- `Cuda.HostIO` maps typed control queues and owned bulk regions (host address,
  CUDA address, or DMA-BUF).

## Hardware surface

- Typed WMMA, WGMMA, TMA, `mbarrier`, bulk-copy, tensor memory (tcgen05)
- Hopper register redistribution via `setmaxnreg`, whole-program compilation only
- Architecture-gated shims fail at compile time off the required SM, not as device `trap`
- Optional in-kernel tracing to Perfetto JSON; kernels that never call it have no
  tracing overhead

## Alpha restrictions

- Hopper register budgets require whole-program CUDA compilation
- Default-stream `launch` does not order against user streams
- Device allocation is a per-block bump arena; `ST.Ref` is thread-private
- Tests skip cleanly without matching hardware — inspect output, do not trust a green skip
