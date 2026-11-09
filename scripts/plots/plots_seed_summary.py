"""Compare larger-trace policies using separate workload panels and seed ranges."""
import statistics

from common import Run, color, label, legend, main, num, ordered, percentage, capacity_axis, line_style


def render(args):
    """Plot per-family seed means and ranges for hit rate, net savings, and evictions."""
    run = Run(args)
    if any(not r.get("family") or not r.get("seed") for r in run.rows):
        raise ValueError("seed summaries require family and seed columns")
    source = run.rows
    groups = {}
    for row in source:
        key = row["family"], row["policy"], num(row, "budget_mib")
        groups.setdefault(key, []).append(row)
    seed_sets = [{r["seed"] for r in group} for group in groups.values()]
    if not seed_sets or any(seeds != seed_sets[0] for seeds in seed_sets):
        raise ValueError("seed comparison requires the same completed seeds in every policy/capacity cell")
    figures = []
    for name, title, ylabel, metric in [
        ("hit_rate", "Seed means · value hit rate", "Value hit rate", lambda r: num(r, "hit_rate")),
        ("net_time_saved", "Seed means · modeled net time savings", "Fraction of uncached tool time saved",
         lambda r: num(r, "net_time_saved_ms") / num(r, "baseline_tool_time_ms")),
        ("evictions", "Seed means · reported eviction pressure", "Reported evicted entries per 1,000 requests",
         lambda r: 1000*num(r, "evictions") / num(r, "requests")),
    ]:
        aggregated = []
        for (family, policy, budget), group in sorted(groups.items()):
            values = [metric(r) for r in group]
            aggregated.append({"workload": family, "policy": policy, "budget_mib": budget,
                "mean": statistics.mean(values), "minimum": min(values), "maximum": max(values),
                "standard_deviation": statistics.stdev(values) if len(values)>1 else 0,
                "seeds": len(values)})
        run.rows = aggregated
        fig, panels = run.grid(title)
        for ax, family in panels:
            rows = [r for r in aggregated if r["workload"] == family]
            for policy in ordered(rows):
                points = sorted([r for r in rows if r["policy"] == policy], key=lambda r: r["budget_mib"])
                xs = [r["budget_mib"] for r in points]
                ax.errorbar(xs, [r["mean"] for r in points],
                            yerr=[[max(0, r["mean"]-r["minimum"]) for r in points],
                                  [max(0, r["maximum"]-r["mean"]) for r in points]],
                            marker="o", lw=2, ms=4, capsize=3, elinewidth=1,
                            color=color(policy), label=label(policy), linestyle=line_style(policy))
            capacity_axis(ax, [r["budget_mib"] for r in rows])
            ax.set_ylabel(ylabel)
            if name != "evictions":
                percentage(ax)
                if name == "hit_rate": ax.set_ylim(0,1)
            else:
                ax.set_ylim(bottom=0)
        legend(fig, panels[0][0])
        figures.append(run.save(fig, f"seed_summary/{name}", aggregated,
            f"Lines = equal-weight mean over {len(seed_sets[0])} seeds; error bars = observed min–max seed range, not confidence intervals.\n"
            "Synthetic result-only replay; normalized net savings as exported by the evaluator. No snapshots admitted."))
    return figures


if __name__ == "__main__":
    main(render)
