"""
Діаграми кроку 12: прогони кроків 10 і 11 з однаковими шкалами осей.
Вхід: посекундні таблиці, які створює hpa_events.py (--out).
  python plot_step12.py --s10 step_10_series.csv --s11 step_11_series.csv --out step_12.png
Потрібен matplotlib.
"""
import argparse
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--s10", required=True)
ap.add_argument("--s11", required=True)
ap.add_argument("--out", default="step_12.png")
ap.add_argument("--p99-0", type=float, default=266.5)
ap.add_argument("--jump-start", type=int, default=30)
ap.add_argument("--jump-end", type=int, default=90)
ap.add_argument("--dpi", type=int, default=150)
a = ap.parse_args()


def load(p):
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    col = lambda k: [float(r[k]) if r[k] != "" else None for r in rows]
    return {k: col(k) for k in ("second", "z_rps", "achieved_2xx", "p99_client_ms",
                                "d", "s", "desired", "cpu_rel_requests")}


BLUE, ORANGE, GRAY, INK = "#0072B2", "#D55E00", "#6b7280", "#1f2937"
data = [("Крок 10: 5 реплік без HPA", load(a.s10)), ("Крок 11: HPA", load(a.s11))]
T = max(len(d["second"]) for _, d in data)

fig, axs = plt.subplots(4, 2, figsize=(13, 12), sharex=True, sharey="row")
fig.patch.set_facecolor("white")
for j, (title, d) in enumerate(data):
    x = d["second"]
    for i in range(4):
        ax = axs[i][j]
        ax.axvspan(a.jump_start, a.jump_end, color="#eef2f7", zorder=0)
        ax.grid(axis="y", color="#e5e7eb", lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(colors=INK, labelsize=9)
    ax = axs[0][j]
    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="bold")
    ax.plot(x, d["z_rps"], color=GRAY, lw=1.6, ls="--", label="задана z(t)")
    ax.plot(x, d["achieved_2xx"], color=BLUE, lw=1.4, label="досягнута (2xx)")
    ax = axs[1][j]
    ax.plot(x, d["p99_client_ms"], color=BLUE, lw=1.4, label="p99 клієнта")
    ax.axhline(2 * a.p99_0, color=ORANGE, lw=1.2, ls=":", label=f"поріг 2·p99₀ = {2*a.p99_0:.0f} мс")
    ax = axs[2][j]
    ax.step(x, d["d"], where="post", color=GRAY, lw=1.8, ls="--", label="d(t) потрібні")
    ax.step(x, d["s"], where="post", color=BLUE, lw=1.8, label="s(t) готові")
    if any(v is not None for v in d["desired"]):
        ax.step(x, d["desired"], where="post", color=ORANGE, lw=1.2, ls=":", label="бажані за HPA")
    ax = axs[3][j]
    cpu = [(xi, v) for xi, v in zip(x, d["cpu_rel_requests"]) if v is not None]
    if cpu:
        ax.plot([c[0] for c in cpu], [c[1] for c in cpu], color=BLUE, lw=1.4, label="CPU / requests")
    else:
        ax.text(0.5, 0.5, "немає даних CPU", transform=ax.transAxes, ha="center", color=GRAY)
    ax.axhline(0.8, color=ORANGE, lw=1.2, ls=":", label="ціль HPA 80 %")
    ax.set_xlabel("секунда прогону", color=INK)
    ax.set_xlim(0, T)

axs[0][0].set_ylabel("запитів/с", color=INK)
axs[1][0].set_ylabel("p99 клієнта, мс", color=INK)
axs[2][0].set_ylabel("репліки", color=INK)
axs[3][0].set_ylabel("CPU відносно requests", color=INK)
axs[0][0].set_ylim(0, 2800)
axs[1][0].set_ylim(0, 5600)
axs[2][0].set_ylim(0, 5.6)
axs[2][0].set_yticks(range(0, 6))
axs[3][0].set_ylim(0, 2.4)
for i in range(4):
    for j in range(2):
        axs[i][j].legend(loc="upper right", fontsize=8, frameon=False)
fig.text(0.01, 0.005, "Сіра смуга: відрізок стрибка (30–90 с). Шкали осей однакові в обох колонках.", fontsize=9, color=GRAY)
fig.tight_layout(rect=(0, 0.02, 1, 1))
fig.savefig(a.out, dpi=a.dpi)
print("Збережено", a.out)