"""Capacity curves with workload means and seed-range error bars."""
import json
import statistics

from common import (Run, color, label, legend, main, num, ordered, percentage,
                    eviction_cells, capacity_axis, zero_capacity_control,
                    aggregate_seeds, seed_errors, SEED_CAPTION)


def render(args):
    """Plot mean hit rate, modeled time savings, and USD savings versus capacity."""
    run = Run(args)
    source = run.rows
    validation_path = run.source / "validation.json"
    validation = {}
    if validation_path.exists():
        groups = {}
        for row in json.loads(validation_path.read_text()):
            groups.setdefault(row.get("family") or row["workload"], []).append(row)
        validation = {key: {field: statistics.mean(num(r, field) for r in group)
                            for field in ("repeat_fraction", "unique_cache_entry_bytes")}
                      for key, group in groups.items()}
    figures = []
    metrics = [("hit_rate", "Value hit rate", "Hit rate", lambda r: num(r, "hit_rate")),
               ("time_saved", "Modeled tool-time savings", "Fraction of baseline time saved",
                lambda r: num(r, "net_time_saved_ms") / num(r, "baseline_tool_time_ms")),
               ("cost_saved", "Modeled cost savings", "Fraction of baseline USD saved",
                lambda r: num(r, "net_cost_saved_usd") / num(r, "baseline_tool_cost_usd"))]
    for name, title, ylabel, metric in metrics:
        denominator = "baseline_tool_cost_usd" if name == "cost_saved" else "baseline_tool_time_ms"
        derived = [{**r, "plotted_value": metric(r)} for r in source
                   if name == "hit_rate" or num(r, denominator) > 0]
        if not derived:
            print(f"skip {name}: no defined normalized values")
            continue
        exported = aggregate_seeds(derived, ["plotted_value"])
        run.rows = exported
        fig, panels = run.grid(f"{title} vs cache capacity")
        for ax, workload in panels:
            rows = [r for r in exported if r["workload"] == workload]
            if not any(num(r, "budget_mib") > 0 for r in rows):
                raise ValueError(f"{workload}: log capacity curves need a positive tested budget")
            controls = []
            for policy in ordered(rows):
                points = sorted([r for r in rows if r["policy"] == policy], key=lambda r: num(r, "budget_mib"))
                curve = [r for r in points if num(r, "budget_mib") > 0]
                controls.extend(num(r, "plotted_value") for r in points if num(r, "budget_mib") == 0)
                ax.errorbar([num(r, "budget_mib") for r in curve], [num(r, "plotted_value") for r in curve],
                            yerr=seed_errors(curve, "plotted_value"), marker="o", ms=4, lw=2,
                            elinewidth=1, capsize=3, color=color(policy), label=label(policy))
            if name == "hit_rate" and workload in validation:
                ax.axhline(validation[workload]["repeat_fraction"], ls=":", color="#777777", lw=1.4,
                           label="Mean full-cache repeat ceiling")
            if workload in validation:
                fits_at = validation[workload]["unique_cache_entry_bytes"] / 1024**2
                minimum = min(num(r, "budget_mib") for r in rows if num(r, "budget_mib") > 0)
                maximum = max(num(r, "budget_mib") for r in rows)
                if minimum <= fits_at <= maximum:
                    ax.axvline(fits_at, ls="--", color="#777777", lw=1.2, label="Mean full catalog fits")
                if fits_at < maximum:
                    ax.axvspan(max(fits_at, minimum), maximum, color="#64748B", alpha=.08, zorder=0)
            raw = [r for r in source if (r.get("family") or r["workload"]) == workload]
            cells = eviction_cells(raw)
            if cells and all(c["maximum_evictions"] == 0 for c in cells):
                ax.text(.97, .06, "No capacity evictions in this sweep", transform=ax.transAxes,
                        ha="right", va="bottom", fontsize=8, color="#475569")
            capacity_axis(ax)
            budgets = sorted({num(r, "budget_mib") for r in rows if num(r, "budget_mib") > 0})
            ax.set_xticks(budgets)
            ax.set_xlim(budgets[0]/1.12, budgets[-1]*1.12)
            zero_capacity_control(ax, controls)
            ax.set_ylabel(ylabel)
            percentage(ax)
            if name == "hit_rate":
                ax.set_ylim(0, 1.01)
            else:
                ax.axhline(0, color="#999999", lw=.7)
        legend(fig, panels[0][0])
        figures.append(run.save(fig, f"capacity/{name}", exported,
            SEED_CAPTION + "\n" +
            "Synthetic estimates include reconstruction; cache overheads/prices follow the input cost model.\n"
            "Only tested positive capacities are shown on the base-2 log axis; zero-budget controls remain off-axis.\n"
            "Catalog/repeat guides use seed means; the full-catalog marker appears only within the tested range.",
            bottom=.19))
    return figures


if __name__ == "__main__":
    main(render)
