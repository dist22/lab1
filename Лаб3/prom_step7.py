"""
Знімає з Prometheus серверні метрики для вікна оцінки сходинки (крок 7-8):
p99 сервера і частку CFS-дроселювання по подах web, RPS по подах (серверний).

Використання (t0 і t1 беруться з рядка "Вікно оцінки (unix)" у підсумку step_6.py):
    python prom_step7.py --t0 1731291000.123 --t1 1731291020.123

Лише стандартна бібліотека Python.
"""
import argparse
import json
import urllib.parse
import urllib.request


def query(prom, q, t):
    url = f"{prom}/api/v1/query?" + urllib.parse.urlencode({"query": q, "time": f"{t:.3f}"})
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if data.get("status") != "success":
        raise SystemExit(f"Помилка Prometheus: {data}")
    return data["data"]["result"]


def by_pod(res):
    out = {}
    for item in res:
        pod = item["metric"].get("pod", "?")
        v = float(item["value"][1])
        if v == v:  # відкинути NaN
            out[pod] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prom", default="http://localhost:9090")
    ap.add_argument("--t0", type=float, required=True, help="початок вікна (unix)")
    ap.add_argument("--t1", type=float, required=True, help="кінець вікна (unix)")
    ap.add_argument("--range", type=int, default=None,
                    help="діапазон rate/increase, с (за замовчуванням t1-t0; "
                         "якщо порожньо/NaN - спробуйте 30)")
    ap.add_argument("--lat-metric", default="http_request_duration_seconds",
                    help="ім'я гістограми затримки сервісу (без _bucket/_count)")
    ap.add_argument("--job", default="web")
    ap.add_argument("--container", default="web")
    a = ap.parse_args()

    rng = a.range or int(round(a.t1 - a.t0))
    m, job, c = a.lat_metric, a.job, a.container

    p99_pod = by_pod(query(a.prom,
        f'histogram_quantile(0.99, sum by (le,pod)(rate({m}_bucket{{job="{job}"}}[{rng}s])))', a.t1))
    p99_all = by_pod(query(a.prom,
        f'histogram_quantile(0.99, sum by (le)(rate({m}_bucket{{job="{job}"}}[{rng}s])))', a.t1))
    thr = by_pod(query(a.prom,
        f'sum by (pod)(increase(container_cpu_cfs_throttled_periods_total{{container="{c}"}}[{rng}s])) / '
        f'sum by (pod)(increase(container_cpu_cfs_periods_total{{container="{c}"}}[{rng}s]))', a.t1))
    rps = by_pod(query(a.prom,
        f'sum by (pod)(rate({m}_count{{job="{job}"}}[{rng}s]))', a.t1))

    # cAdvisor оновлює лічильники рідко, тому increase() за 20 с інколи порожній.
    # Для таких подів рахуємо різницю лічильників у моменти t1 і t0 (позначка *).
    def counter(metric, t):
        return by_pod(query(a.prom, f'sum by (pod)({metric}{{container="{c}"}})', t))
    th1 = counter("container_cpu_cfs_throttled_periods_total", a.t1)
    th0 = counter("container_cpu_cfs_throttled_periods_total", a.t0)
    pe1 = counter("container_cpu_cfs_periods_total", a.t1)
    pe0 = counter("container_cpu_cfs_periods_total", a.t0)
    thr_delta = set()
    for p in set(th1) & set(th0) & set(pe1) & set(pe0):
        if p not in thr and pe1[p] - pe0[p] > 0:
            thr[p] = (th1[p] - th0[p]) / (pe1[p] - pe0[p])
            thr_delta.add(p)

    pods = sorted(set(p99_pod) | set(thr) | set(rps))
    print(f"Вікно: {a.t0:.3f} .. {a.t1:.3f}  (діапазон {rng} с)\n")
    print(f"{'под':<40} {'RPS':>8} {'p99 серв., ms':>14} {'дроселювання':>13}")
    for p in pods:
        r = f"{rps[p]:.1f}" if p in rps else "-"
        l = f"{p99_pod[p]*1000:.1f}" if p in p99_pod else "-"
        t = (f"{thr[p]:.2%}" + ("*" if p in thr_delta else "")) if p in thr else "-"
        print(f"{p:<40} {r:>8} {l:>14} {t:>13}")
    if thr_delta:
        print("* дроселювання за різницею лічильників на краях вікна "
              "(точність обмежена кроком оновлення cAdvisor, ~10-15 с)")

    print()
    if p99_all:
        print(f"p99 сервера (всі поди): {next(iter(p99_all.values()))*1000:.1f} ms")
    if thr:
        vals = list(thr.values())
        print(f"Дроселювання: середнє за подами {sum(vals)/len(vals):.2%}, "
              f"найбільше {max(vals):.2%} ({max(thr, key=thr.get)})")
    if rps:
        print("RPS по подах (серверний): найбільше "
              f"{max(rps.values()):.1f} ({max(rps, key=rps.get)}), "
              f"найменше {min(rps.values()):.1f} ({min(rps, key=rps.get)})")
    if not pods:
        print("Порожньо: перевірте мітку pod у метриках web і ім'я --lat-metric.")


if __name__ == "__main__":
    main()