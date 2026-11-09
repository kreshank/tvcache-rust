# Neural-policy merge and result compatibility

The 2026-11-08 integration combines local commit `91640d6` (large traces,
optimized replay, plotting and seed aggregation) with `origin/main` at
`c907985` (learned policies, training/evaluation and validation results).
`codex/pre-pull-2026-11-08` preserves the local commit before the merge.

## What was preserved

The only textual conflict was `.gitignore`: the resolution keeps both the
generated-trace exclusions and the incoming `runs/` exclusion. In replay,
cached subtree membership/byte bookkeeping remains in place, alongside the
new `replay_observed` API and eviction-observer callback used for training data.
The other 23 files changed by the local commit were preserved byte-for-byte.

Existing local baseline result directories are separate from the incoming
`results/learned-1g-val` directory. All 2,257 pre-existing generated files kept
their sizes and modification times; content hashes also matched for 1,625
smaller reports, tables, plots and metadata files. No existing run was replaced.

## Checks

- All 33 Rust tests and nine baseline-plotting tests passed.
- FIFO, linear, LRU, LFU and persistent LFU produced byte-identical decisions
  before and after merging on the 9,613-access balanced fixture at 1 MiB.
- The merged linear replay matched all 199,507 decisions from the completed
  large balanced trace at 1 GiB.
- The saved `small-belady` model ran through the merged replay. Its decisions
  passed full-entry byte-budget checks and independent evaluator validation.
- The incoming learned-results plotting entry point generated its two figures.

These are integration checks, not a new neural benchmark sweep. Exact decision
comparisons exclude the original enforcer because its equal-score ties vary.

## CSVs still need explicit export compatibility

Merging the code does not convert the compact neural CSV into the baseline
plotting schema. In particular, `saved_fraction_of_achievable` uses repeatable
tool work as its denominator; the baseline plots normalize net savings by all
uncached tool work. Preserve the full evaluator metrics when exporting rows.
Use matching trace hashes, seeds, budgets, split and cost assumptions for a
shared comparison. The existing neural validation suite and local larger-trace
suite use different generation settings and seeds, so keep separate run folders.

### Eviction-count distinction

Do not blindly rename native `evicted_entries` to evaluator `evictions`.
The native counter includes an entry inserted and removed in the same event.
The exported decision represents this as a bypass; the evaluator counts an
admission rejection instead of an eviction of an already resident entry.

The small-belady integration check had 2,687 native evicted entries, including
534 immediate incoming discards, and 2,153 evaluator evictions. Hits agreed
at 5,867 out of 9,613 requests. This accounting distinction predates the merge.
For the existing baseline plot contract, export `metrics["evictions"]` from
the full evaluator report. The handoff's export helper already does this; its
earlier CSV column-mapping note needs this qualification.

## Historical result provenance

Existing results retain their original code/binary hashes. The merged binary
has a different hash, so the large-trace runner deliberately refuses to resume
an old directory under changed code. Start a new output directory for merged
experiments; do not rewrite the old `run.json` to bypass that check.
