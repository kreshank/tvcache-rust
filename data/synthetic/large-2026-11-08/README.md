# Large logical-cache traces

Twelve synthetic traces, four families × seeds 42/43/44. Catalogs contain about 9–14 GiB of logical cache-entry bytes per trace. See [generation report](../../../results/large-traces-2026-11-08/README.md) for exact sizes, timings, and assumptions.

| Trace | Catalog GiB | Manifest |
| --- | ---: | --- |
| balanced seed 42 | 11.01 | [manifest/config](balanced/balanced-seed-42/manifest.json) |
| expensive_reuse seed 42 | 13.20 | [manifest/config](expensive_reuse/expensive_reuse-seed-42/manifest.json) |
| memory_pressure seed 42 | 9.33 | [manifest/config](memory_pressure/memory_pressure-seed-42/manifest.json) |
| popularity_shift seed 42 | 13.53 | [manifest/config](popularity_shift/popularity_shift-seed-42/manifest.json) |
| balanced seed 43 | 11.12 | [manifest/config](balanced/balanced-seed-43/manifest.json) |
| expensive_reuse seed 43 | 13.35 | [manifest/config](expensive_reuse/expensive_reuse-seed-43/manifest.json) |
| memory_pressure seed 43 | 9.34 | [manifest/config](memory_pressure/memory_pressure-seed-43/manifest.json) |
| popularity_shift seed 43 | 13.22 | [manifest/config](popularity_shift/popularity_shift-seed-43/manifest.json) |
| balanced seed 44 | 11.34 | [manifest/config](balanced/balanced-seed-44/manifest.json) |
| expensive_reuse seed 44 | 13.45 | [manifest/config](expensive_reuse/expensive_reuse-seed-44/manifest.json) |
| memory_pressure seed 44 | 9.60 | [manifest/config](memory_pressure/memory_pressure-seed-44/manifest.json) |
| popularity_shift seed 44 | 13.61 | [manifest/config](popularity_shift/popularity_shift-seed-44/manifest.json) |

Pass an individual leaf directory to the evaluator or replay CLI. The suite root itself is not a trace directory.

```sh
python3 -m tvcache_eval validate data/synthetic/large-2026-11-08/balanced/balanced-seed-42
```
