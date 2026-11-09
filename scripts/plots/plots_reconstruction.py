"""Show modeled net savings at a selected capacity, averaged across seeds."""
from common import (Run, color, label, main, num, ordered, percentage, select_budget,
                    aggregate_seeds, seed_errors, SEED_CAPTION)


def render(args):
    """Plot mean net savings with one seed-range error bar per policy."""
    run = Run(args)
    derived = []
    for workload in sorted({r["workload"] for r in run.rows}):
        rows = [r for r in run.rows if r["workload"] == workload and num(r, "budget_mib") > 0]
        budget, selected = select_budget(rows, args.budget_position)
        for row in selected:
            baseline = num(row, "baseline_tool_time_ms")
            if baseline <= 0:
                raise ValueError("baseline tool time must be positive")
            derived.append({**row, "net_fraction": num(row, "net_time_saved_ms")/baseline})
    exported = aggregate_seeds(derived, ["net_fraction"])
    run.rows = exported
    fig, panels = run.grid("Modeled net time savings at selected capacity")
    for ax, workload in panels:
        rows = [r for r in exported if r["workload"] == workload]
        policies = ordered(rows)
        rows.sort(key=lambda r: policies.index(r["policy"]))
        for i, row in enumerate(rows):
            ax.bar(i, num(row, "net_fraction"), color=color(row["policy"]),
                   yerr=seed_errors([row], "net_fraction"), capsize=3,
                   error_kw={"elinewidth": 1})
        ax.set_xticks(range(len(rows)), [label(r["policy"]) for r in rows], rotation=25, ha="right")
        ax.set_title(f"{workload.replace('_', ' ')} · {num(rows[0], 'budget_mib'):g} MiB")
        ax.set_ylabel("Fraction of uncached\ntool time saved")
        ax.axhline(0, lw=.8, color="#888888")
        percentage(ax)
    return [run.save(fig, "reconstruction/net_savings", exported,
        SEED_CAPTION + "\n" +
        "Bars = modeled net savings after reconstruction and modeled overheads; one error bar per policy.\n"
        f"Each workload uses its {args.budget_position} nonzero tested capacity; synthetic costs, not training wall-clock savings.",
        bottom=.23)]


if __name__ == "__main__":
    main(render)
