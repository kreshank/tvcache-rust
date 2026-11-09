"""Matched comparisons against the original enforcer, averaged across seeds."""
from common import (ORIGINAL, Run, color, label, legend, main, num, ordered, percentage,
                    capacity_axis, zero_capacity_control, aggregate_seeds, seed_errors, SEED_CAPTION)


def render(args):
    """Plot paired time improvement and diagnostic callback overhead with seed ranges."""
    run = Run(args)
    source = run.rows
    baseline = {(r["workload"], num(r, "budget_mib")): r for r in source if r["policy"] == ORIGINAL}
    derived = []
    for row in source:
        key = row["workload"], num(row, "budget_mib")
        if key not in baseline:
            raise ValueError(f"{key}: original-enforcer rows are required at every matched budget")
        original_ms = num(baseline[key], "modeled_request_ms")
        if original_ms <= 0:
            raise ValueError("original modeled time must be positive for relative comparison")
        derived.append({**row, "time_reduction_vs_original": 1-num(row, "modeled_request_ms")/original_ms})
    exported = aggregate_seeds(derived, ["time_reduction_vs_original"])
    run.rows = exported
    figures = []
    fig, panels = run.grid("Modeled execution time vs original enforcer")
    for ax, workload in panels:
        rows = [r for r in exported if r["workload"] == workload]
        controls = []
        for policy in ordered(rows):
            points = sorted([r for r in rows if r["policy"] == policy], key=lambda r: num(r, "budget_mib"))
            curve = [r for r in points if num(r, "budget_mib") > 0]
            controls.extend(num(r, "time_reduction_vs_original") for r in points if num(r, "budget_mib") == 0)
            ax.errorbar([num(r, "budget_mib") for r in curve], [num(r, "time_reduction_vs_original") for r in curve],
                        yerr=seed_errors(curve, "time_reduction_vs_original"), marker="o", ms=4,
                        color=color(policy), lw=2, capsize=3, elinewidth=1, label=label(policy))
        ax.axhline(0, color="#333333", lw=1)
        capacity_axis(ax)
        zero_capacity_control(ax, controls)
        ax.set_ylabel("Modeled time reduction\nvs original (higher is better)")
        percentage(ax)
    legend(fig, panels[0][0])
    figures.append(run.save(fig, "tradeoffs/vs_original", exported,
        SEED_CAPTION + "\n" +
        "Baseline ratios are paired by trace seed and capacity before averaging; positive = less modeled tool-work time.\n"
        "Original is the repository enforcer; equal-score ties may vary. Base-2 log capacity; zero controls off-axis."))
    overhead = [{**r, "plotted_microseconds_per_request": num(r, "rust_policy_ns_per_request")/1000}
                for r in source if r["policy"] != ORIGINAL and num(r, "budget_mib") > 0]
    overhead_rows = aggregate_seeds(overhead, ["plotted_microseconds_per_request"])
    run.rows = overhead_rows
    fig, panels = run.grid("Rust policy callback cost per request")
    for ax, workload in panels:
        rows = [r for r in overhead_rows if r["workload"] == workload]
        for policy in ordered(rows):
            points = sorted([r for r in rows if r["policy"] == policy], key=lambda r: num(r, "budget_mib"))
            ax.errorbar([num(r, "budget_mib") for r in points],
                        [num(r, "plotted_microseconds_per_request") for r in points],
                        yerr=seed_errors(points, "plotted_microseconds_per_request"),
                        marker="o", ms=4, lw=2, capsize=3, elinewidth=1, color=color(policy), label=label(policy))
        capacity_axis(ax)
        ax.set_ylabel("Policy callback time (µs/request)")
        ax.set_yscale("symlog", linthresh=1)
    legend(fig, panels[0][0])
    figures.append(run.save(fig, "tradeoffs/policy_overhead", overhead_rows,
        SEED_CAPTION + "\n" +
        "Rust callbacks only; candidate construction/engine work excluded. Original enforcer is not instrumented.\n"
        "Concurrent local runs: diagnostic timings, not isolated microbenchmarks. Base-2 log capacity."))
    return figures


if __name__ == "__main__":
    main(render)
