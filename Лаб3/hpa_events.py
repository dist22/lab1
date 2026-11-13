"""
Обробка прогону профілю (кроки 11-12): події HPA і метрики еластичності.

Бере посекундний CSV генератора і ряди з Prometheus за час прогону:
  s(t)       kube_deployment_status_replicas_ready            (готові поди)
  desired    kube_horizontalpodautoscaler_status_desired_replicas (лише для прогону з HPA)
  cpu        середнє використання CPU подів відносно requests.cpu

Друкує: чотири події кроку 11, метрики кроку 12 (theta_U, theta_O, a_U, a_O, W,
секунди порушення порогу, non-2xx) і зберігає посекундну таблицю для діаграм.

Приклади:
  python hpa_events.py --csv step_11.csv --out step_11_series.csv --hpa
  python hpa_events.py --csv step_10.csv --out step_10_series.csv
Лише стандартна бібліотека Python.
"""
import argparse
import csv
import json
import urllib.parse
import urllib.request


def qrange(prom, q, t0, t1, step=1):
    url = f"{prom}/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": q, "start": f"{t0:.3f}", "end": f"{t1:.3f}", "step": step})
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    if data.get("status") != "success":
        raise SystemExit(f"Помилка Prometheus: {data}")
    res = data["data"]["result"]
    if not res:
        return {}
    return {float(ts): float(v) for ts, v in res[0]["values"] if v != "NaN"}


def at(series, t, default=None):
    """Значення на момент t: останнє відоме (ряд сталий між точками збору)."""
    if not series:
        return default
    keys = [k for k in series if k <= t + 1e-6]
    return series[max(keys)] if keys else default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="посекундний CSV генератора")
    ap.add_argument("--out", default=None, help="куди зберегти посекундну таблицю")
    ap.add_argument("--prom", default="http://localhost:9090")
    ap.add_argument("--hpa", action="store_true", help="прогін з HPA (брати desired з HPA)")
    ap.add_argument("--hpa-name", default="web-hpa")
    ap.add_argument("--deployment", default="web")
    ap.add_argument("--requests-cpu", type=float, default=0.5, help="requests.cpu, ядер")
    ap.add_argument("--R", type=int, default=5)
    ap.add_argument("--jump-start", type=int, default=30)
    ap.add_argument("--jump-end", type=int, default=90)
    ap.add_argument("--p99-jump", type=float, default=1525.2,
                    help="p99 клієнта на відрізку стрибка кроку 10, мс (поріг 1,2x)")
    ap.add_argument("--p99-0", type=float, default=266.5,
                    help="p99_0: p99 клієнта на 1-му відрізку прогону без HPA, мс (поріг 2x)")
    ap.add_argument("--x", default="1:2126.3,2:2484.8,3:2038.0,5:2310.8",
                    help="X(N) з кроку 7; відсутнє N береться з кривої закону")
    ap.add_argument("--sigma", type=float, default=0.9226)
    ap.add_argument("--kappa", type=float, default=0.0)
    a = ap.parse_args()

    rows = [r for r in csv.DictReader(open(a.csv, encoding="utf-8")) if r["step"] != ""]
    T = len(rows)
    start = float(rows[0]["ts"])
    t_end = start + T

    # X(N): виміряні значення + крива закону для відсутніх N
    X = {int(k): float(v) for k, v in (p.split(":") for p in a.x.split(","))}
    for n in range(1, a.R + 1):
        if n not in X:
            X[n] = X[1] * n / (1 + a.sigma * (n - 1) + a.kappa * n * (n - 1))

    def d_of(z):
        for n in range(1, a.R + 1):
            if X[n] >= z:
                return n
        return a.R

    s_ser = qrange(a.prom,
                   f'sum(kube_deployment_status_replicas_ready{{deployment="{a.deployment}"}})',
                   start - 10, t_end + 1)
    des_ser = {}
    if a.hpa:
        des_ser = qrange(a.prom,
                         f'max(kube_horizontalpodautoscaler_status_desired_replicas'
                         f'{{horizontalpodautoscaler="{a.hpa_name}"}})', start - 10, t_end + 1)
    cpu_ser = qrange(a.prom,
                     f'avg(sum by (pod)(rate(container_cpu_usage_seconds_total'
                     f'{{container="{a.deployment}"}}[20s])))/{a.requests_cpu}', start - 10, t_end + 1)
    if not s_ser:
        raise SystemExit("Порожній ряд kube_deployment_status_replicas_ready: перевірте Prometheus.")
    if a.hpa and not des_ser:
        raise SystemExit("Порожній ряд desired_replicas: kube-state-metrics не бачить HPA "
                         "(потрібні права на horizontalpodautoscalers у ClusterRole).")

    z = [int(float(r["target_rps"])) for r in rows]
    ach = [int(r["achieved_2xx_rps"]) for r in rows]
    p99 = [float(r["p99_sec"]) * 1000 for r in rows]
    s = [int(round(at(s_ser, start + t, 0))) for t in range(T)]
    d = [d_of(x) for x in z]
    des = [int(round(at(des_ser, start + t, 0))) for t in range(T)] if a.hpa else None
    cpu = [at(cpu_ser, start + t) for t in range(T)]

    js, je = a.jump_start, a.jump_end
    print(f"Прогін: {T} с, старт {start:.3f}, стрибок {js}..{je} с\n")

    if a.hpa:
        print("=== Події кроку 11 ===")
        base = des[js - 1]
        e1 = next((t for t in range(js, je) if des[t] != base), None)
        print(f"1. Перша зміна бажаної кількості реплік: "
              + (f"{e1 - js} с від початку стрибка (t={e1} с, {base} -> {des[e1]})" if e1 is not None else "не досягнуто"))
        smax = max(s)
        e2 = next((t for t in range(js, T) if s[t] >= smax), None)
        print(f"2. Готовність найбільшої кількості реплік ({smax}): "
              + (f"{e2 - js} с (t={e2} с)" if e2 is not None and e2 < je else "не досягнуто до кінця стрибка")
              + (f" [досягнуто на {e2 - js} с, уже після стрибка]" if e2 is not None and e2 >= je else ""))
        thr = 1.2 * a.p99_jump
        e3 = None
        for t in range(js, je):
            if t + 10 <= T and all(p99[u] < thr for u in range(t, t + 10)):
                e3 = t
                break
        print(f"3. p99 клієнта 10 с поспіль < {thr:.0f} мс (1,2 x {a.p99_jump}): "
              + (f"{e3 - js} с (t={e3} с)" if e3 is not None else "не досягнуто"))
        ref = s[je - 1]
        e4 = next((t for t in range(je, T) if s[t] < ref), None)
        print(f"4. Перше зменшення готових реплік після кінця стрибка (було {ref}): "
              + (f"{e4 - je} с (t={e4} с, {ref} -> {s[e4]})" if e4 is not None else "не досягнуто"))
        print()

    print("=== Метрики еластичності (крок 12) ===")
    thU = sum(1 for t in range(T) if s[t] < d[t]) / T
    thO = sum(1 for t in range(T) if s[t] > d[t]) / T
    aU = sum(max(d[t] - s[t], 0) for t in range(T)) / T
    aO = sum(max(s[t] - d[t], 0) for t in range(T)) / T
    W = sum(s)
    thr2 = 2 * a.p99_0
    viol = sum(1 for p in p99 if p > thr2)
    non2xx = sum(int(r["non_2xx"]) for r in rows)
    tmo = sum(int(r["timeout"]) + int(r["conn_error"]) for r in rows)
    print(f"theta_U = {thU:.4f}   theta_O = {thO:.4f}")
    print(f"a_U     = {aU:.4f}   a_O     = {aO:.4f}")
    print(f"W       = {W} репліко-секунд (T = {T} с)")
    print(f"Секунд порушення порогу (p99 > 2 x {a.p99_0} = {thr2:.0f} мс): {viol}")
    print(f"Відповідей не 2xx: {non2xx}   (таймаути + помилки з'єднання: {tmo})")
    print("d(t) за X(N): " + ", ".join(f"X({n})={X[n]:.0f}" for n in sorted(X)))

    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["second", "z_rps", "achieved_2xx", "p99_client_ms", "d", "s", "desired", "cpu_rel_requests"])
            for t in range(T):
                w.writerow([t, z[t], ach[t], round(p99[t], 1), d[t], s[t],
                            des[t] if des else "", "" if cpu[t] is None else round(cpu[t], 3)])
        print(f"\nПосекундну таблицю збережено: {a.out}")


if __name__ == "__main__":
    main()