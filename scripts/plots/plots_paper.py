"""Versioned paper values beside clearly separate local replay summaries."""
import matplotlib.pyplot as plt
from common import (REFERENCES, Run, color, label, legend, main, num, ordered, percentage,
                    read_csv, select_budget, aggregate_seeds, seed_errors, SEED_CAPTION)


def render(args):
    """Plot paper hit-rate and median-speedup reference panels beside local estimates."""
    run = Run(args)
    paper = read_csv(REFERENCES / "workloads.csv", ["setting", "hit_rate", "median_speedup", "source", "location"])
    local = []
    for workload in sorted({r["workload"] for r in run.rows}):
        rows = [r for r in run.rows if r["workload"] == workload and num(r, "budget_mib") > 0]
        if not rows:
            raise ValueError(f"{workload}: needs nonzero budget")
        _, selected = select_budget(rows, args.budget_position)
        local.extend(selected)
    figures = []
    for metric in ("hit_rate", "speedup"):
        summary = aggregate_seeds([{**r, "plotted_value": num(r, metric)} for r in local], ["plotted_value"])
        workloads = sorted({r["workload"] for r in summary})
        local_width = max(7, .85 * len(workloads))
        fig, axes = plt.subplots(1, 2, figsize=(7 + local_width, 7),
                                 gridspec_kw={"width_ratios": [7, local_width]})
        fig.suptitle("TVCache paper context · unmatched workloads", fontsize=17, y=.98)
        field = "hit_rate" if metric == "hit_rate" else "median_speedup"
        reported = [r for r in paper if r[field] != ""]
        values = [num(r, field) for r in reported]
        axes[0].bar(range(len(reported)), values, color="#64748B", width=.65)
        axes[0].set_xticks(range(len(reported)), [r["setting"].replace(" ", "\n", 1) for r in reported],
                          rotation=25, ha="right", fontsize=8)
        axes[0].set_title("Paper: measured real workloads (v1)")
        axes[0].set_ylabel("Mean hit rate over epochs" if metric == "hit_rate" else "Median tool-call speedup (×)")
        for i, value in enumerate(values):
            axes[0].annotate(f"{100*value:.1f}%" if metric == "hit_rate" else f"{value:.2f}×",
                             (i, value), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
        policies = ordered(summary)
        width = .8 / len(policies)
        exported = [{**r, "panel": "paper", "plotted_value": num(r, field)} for r in reported]
        for i, policy in enumerate(policies):
            points = [next((r for r in summary if r["workload"] == w and r["policy"] == policy), None) for w in workloads]
            xs, ys, selected = [], [], []
            for j, row in enumerate(points):
                if row is None:
                    continue
                value = num(row, "plotted_value")
                xs.append(j + (i - (len(policies)-1)/2)*width)
                ys.append(value)
                selected.append(row)
                exported.append({**row, "panel": "local", "plotted_value": value})
            axes[1].bar(xs, ys, yerr=seed_errors(selected, "plotted_value"),
                        capsize=2, error_kw={"elinewidth": 1},
                        width=width, color=color(policy), label=label(policy))
        axes[1].set_xticks(range(len(workloads)),
            [w.replace("_", "\n").replace("-seed-", "\nseed ") + "\n" +
             f"{num(next(r for r in summary if r['workload']==w), 'budget_mib'):g} MiB" for w in workloads],
            fontsize=8)
        axes[1].set_title(f"Local: synthetic replay, {args.budget_position} nonzero capacity")
        axes[1].set_ylabel("Value hit rate over accesses" if metric == "hit_rate" else "Modeled total-tool-work speedup (×)")
        if metric == "hit_rate":
            for ax in axes:
                percentage(ax)
                ax.set_ylim(0, 1)
        else:
            for ax in axes:
                ax.axhline(1, color="#777777", ls=":", lw=1)
        legend(fig, axes[1])
        figures.append(run.save(fig, f"paper/{metric}_context", exported,
            SEED_CAPTION + "\n" +
            "Paper: arxiv.org/html/2602.10986v1, §§4.1–4.3 / Table 2; transcribed summaries, no seed samples/error bars.\n"
            "Different workloads and estimators: contextual panels only. Local total-work speedup is NOT the paper's median tool-call speedup.",
            bottom=.25, top=.80, wspace=.30))
    return figures


if __name__ == "__main__":
    main(render)
