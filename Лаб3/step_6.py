"""
Генератор навантаження (open-loop) для лабораторної роботи 3, варіант 23 (R = 5).

Модель з'єднань (крок 6), діє в усіх прогонах:
  * 8 * R постійних з'єднань (R = --replicas-max), створюються ОДИН РАЗ на весь прогін
    і не залежать від інтенсивності;
  * кожне з'єднання закривається після 100 запитів, замість нього відкривається нове.

Режими:
  step     ступінчастий профіль (крок 7): прогрів, далі сходинки по 30 с,
           середні за останні 20 с сходинки;
  profile  список відрізків "тривалість:інтенсивність" (кроки 10-12),
           наприклад  --profile "30:104,60:690,90:104".

Виходи:
  <csv>            посекундна таблиця (ts = unix-час, для звірки з Prometheus);
  <csv>_pods.csv   кількість 2xx-відповідей за секунду на кожен под (заголовок X-Pod).
"""
import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from collections import defaultdict

import aiohttp
import numpy as np
import pandas as pd

BASE_URL = "http://localhost:8088"
TIMEOUT_SEC = 5.0
TICK = 0.01            # планування пачками по 10 мс
EVAL_SKIP = 10         # перші 10 с сходинки - перехідні (оцінка за останні 20 с)
REQS_PER_CONN = 100    # закрити з'єднання після 100 запитів


class Bucket:
    __slots__ = ("sent", "ok", "http", "timeout", "conn", "lats")

    def __init__(self):
        self.sent = self.ok = self.http = self.timeout = self.conn = 0
        self.lats = []  # затримки лише 2xx


class Timeline:
    def __init__(self):
        self.start = 0.0
        self.start_epoch = 0.0
        self.b = defaultdict(Bucket)
        self.pods = defaultdict(lambda: defaultdict(int))  # sec -> pod -> 2xx
        self.target = {}
        self.step = {}
        self.printed = -1


# ---------------------------------------------------------------- виведення

def row_values(tl, sec):
    b = tl.b.get(sec) or Bucket()
    if b.lats:
        p50, p95, p99 = (float(np.percentile(b.lats, q)) for q in (50, 95, 99))
    else:
        p50 = p95 = p99 = 0.0
    step_raw = tl.step.get(sec, "")
    return {
        "second": sec,
        "ts": round(tl.start_epoch + sec, 3),
        "step": "W" if step_raw == 0 else str(step_raw),
        "target_rps": tl.target.get(sec, 0),
        "actual_send_rps": b.sent,
        "achieved_2xx_rps": b.ok,
        "non_2xx": b.http,
        "timeout": b.timeout,
        "conn_error": b.conn,
        "p50_sec": round(p50, 5),
        "p95_sec": round(p95, 5),
        "p99_sec": round(p99, 5),
    }


def print_row(tl, sec):
    r = row_values(tl, sec)
    bad = r["non_2xx"] or r["timeout"] or r["conn_error"]
    pre, suf = ("\033[91m", "\033[0m") if bad else ("", "")
    print(f"{pre}t={sec:4d}s  step={r['step']:>2}  target={r['target_rps']:6d}  "
          f"sent={r['actual_send_rps']:6d}  2xx={r['achieved_2xx_rps']:6d}  "
          f"non2xx={r['non_2xx']:5d}  tmo={r['timeout']:5d}  conn={r['conn_error']:5d}  "
          f"p50={r['p50_sec']*1000:7.1f}  p95={r['p95_sec']*1000:7.1f}  "
          f"p99={r['p99_sec']*1000:7.1f} ms{suf}", flush=True)


async def reporter(tl):
    while True:
        await asyncio.sleep(0.2)
        done = int(time.perf_counter() - tl.start) - 1
        while tl.printed < done:
            tl.printed += 1
            print_row(tl, tl.printed)


def flush_remaining(tl):
    last = max(list(tl.b.keys()) + list(tl.target.keys()) + [-1])
    while tl.printed < last:
        tl.printed += 1
        print_row(tl, tl.printed)


# ---------------------------------------------------------------- підготовка бази

def extract_ids(data):
    items = data.get("items", []) if isinstance(data, dict) else data
    return [i["id"] for i in items if isinstance(i, dict) and "id" in i]


async def create_one(session, sem):
    payload = {
        "patientCode": f"PAT-{random.randint(1000, 9999)}",
        "deviceType": "Pacemaker",
        "manufacturer": "MedTech",
        "serialNumber": f"SN-{uuid.uuid4().hex[:12]}",
        "installationDate": "2026-01-01T00:00:00Z",
        "lifespanYears": 5,
    }
    async with sem:
        try:
            async with session.post(f"{BASE_URL}/implants", json=payload) as r:
                if r.status not in (200, 201):
                    return None
                try:
                    return (await r.json())["id"]
                except Exception:
                    loc = r.headers.get("Location")
                    return loc.rstrip("/").split("/")[-1] if loc else None
        except Exception:
            return None


async def seed_ids(session, n=100):
    print(f"[*] Перевірка бази на наявність {n} записів...")
    ids = []
    try:
        async with session.get(f"{BASE_URL}/implants?limit={n}") as r:
            if r.status == 200:
                ids = extract_ids(await r.json())
    except Exception:
        pass
    sem = asyncio.Semaphore(20)
    for attempt in range(1, 4):
        needed = n - len(ids)
        if needed <= 0:
            break
        print(f"[*] Створюємо {needed} об'єктів (спроба {attempt})...")
        created = await asyncio.gather(*(create_one(session, sem) for _ in range(needed)))
        ids.extend(i for i in created if i)
    if not ids:
        sys.exit("[!] Не вдалося ні отримати, ні створити жодного об'єкта.")
    return ids[:n]


# ---------------------------------------------------------------- запити і з'єднання

async def execute_one_request(session, url, sched, tl):
    now = time.perf_counter()
    tl.b[int(now - tl.start)].sent += 1

    # Запит прострочений ще в черзі (генератор не встигає / сервіс перевантажений)
    if now - sched > TIMEOUT_SEC:
        tl.b[int(now - tl.start)].timeout += 1
        return False  # по з'єднанню нічого не надсилалося

    kind, pod = "conn", None
    try:
        async with session.get(url) as resp:
            await resp.read()
            if 200 <= resp.status < 300:
                kind = "ok"
                pod = resp.headers.get("X-Pod", "?")
            else:
                kind = "http"
    except asyncio.TimeoutError:
        kind = "timeout"
    except Exception:
        kind = "conn"

    comp = time.perf_counter()
    sec = int(comp - tl.start)
    b = tl.b[sec]
    if kind == "ok":
        b.ok += 1
        b.lats.append(max(0.0, comp - sched))  # від запланованого моменту (open-loop)
        tl.pods[sec][pod] += 1
    elif kind == "http":
        b.http += 1
    elif kind == "timeout":
        b.timeout += 1
    else:
        b.conn += 1
    return True


async def connection_worker(queue, tl, stop_event):
    """Одне постійне з'єднання: після REQS_PER_CONN запитів сесія закривається і відкривається нова."""
    while not stop_event.is_set():
        connector = aiohttp.TCPConnector(limit=1, force_close=False)
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                n = 0
                while n < REQS_PER_CONN and not stop_event.is_set():
                    try:
                        url, sched = await asyncio.wait_for(queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    if await execute_one_request(session, url, sched, tl):
                        n += 1  # лічимо лише запити, які реально пішли по з'єднанню
        except Exception:
            await asyncio.sleep(0.1)


async def run_segment(tl, queue, url_tpl, ids, rps, duration, offset, seg_no):
    """Планує запити з інтенсивністю rps протягом duration секунд (open-loop)."""
    for s in range(offset, offset + duration):
        tl.target[s] = rps
        tl.step[s] = seg_no
    for k in range(int(duration / TICK)):
        tick_time = tl.start + offset + k * TICK
        delay = tick_time - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            await asyncio.sleep(0)  # поступитися циклу подій, якщо відстаємо
        n = int(rps * (k + 1) * TICK + 1e-9) - int(rps * k * TICK + 1e-9)
        for _ in range(n):
            url = url_tpl.format(id=random.choice(ids)) if ids else url_tpl
            queue.put_nowait((url, tick_time))


# ---------------------------------------------------------------- статистика

def window(offset, duration, skip=EVAL_SKIP):
    return range(offset + skip, offset + duration)


def avg_2xx(tl, offset, duration, skip=EVAL_SKIP):
    secs = list(window(offset, duration, skip))
    vals = [tl.b[s].ok if s in tl.b else 0 for s in secs]
    return (statistics.mean(vals) if vals else 0.0,
            statistics.pstdev(vals) if len(vals) > 1 else 0.0)


def pod_avgs(tl, offset, duration, skip=EVAL_SKIP):
    secs = list(window(offset, duration, skip))
    totals = defaultdict(int)
    for s in secs:
        for pod, c in tl.pods.get(s, {}).items():
            totals[pod] += c
    return {pod: c / len(secs) for pod, c in totals.items()}


def window_p99(tl, offset, duration, skip=EVAL_SKIP):
    """p99 клієнта за вікном: (об'єднана вибірка, середнє посекундних p99), с."""
    secs = list(window(offset, duration, skip))
    pooled = [x for s in secs if s in tl.b for x in tl.b[s].lats]
    per_sec = [float(np.percentile(tl.b[s].lats, 99)) for s in secs
               if s in tl.b and tl.b[s].lats]
    return (float(np.percentile(pooled, 99)) if pooled else 0.0,
            statistics.mean(per_sec) if per_sec else 0.0)


def save_csv(tl, path):
    if not (tl.b or tl.target):
        return
    last = max(list(tl.b.keys()) + list(tl.target.keys()))
    pd.DataFrame([row_values(tl, s) for s in range(last + 1)]).to_csv(path, index=False)
    rows = [{"second": s, "ts": round(tl.start_epoch + s, 3), "pod": p, "rps_2xx": c}
            for s in sorted(tl.pods) for p, c in tl.pods[s].items()]
    pods_path = path[:-4] + "_pods.csv" if path.endswith(".csv") else path + "_pods.csv"
    pd.DataFrame(rows).to_csv(pods_path, index=False)
    print(f"[*] Збережено: {path} та {pods_path}")


# ---------------------------------------------------------------- режими

async def run_step_mode(tl, queue, url_tpl, ids, args, summary):
    offset = 0
    print(f"\n=== ПРОГРІВ ({args.warmup_duration} с, {args.warmup_rps} RPS) ===")
    await run_segment(tl, queue, url_tpl, ids, args.warmup_rps, args.warmup_duration, offset, 0)
    offset += args.warmup_duration

    rps, step_no, drops = args.step_increment, 1, 0
    while step_no <= args.max_steps:
        print(f"\n=== СХОДИНКА {step_no} (target {rps} RPS, {args.step_duration} с, "
              f"оцінка за останні {args.step_duration - EVAL_SKIP} с) ===")
        await run_segment(tl, queue, url_tpl, ids, rps, args.step_duration, offset, step_no)
        avg, sd = avg_2xx(tl, offset, args.step_duration)
        summary.append((step_no, rps, avg, sd, offset))
        print(f"--- Сходинка {step_no}: середня 2xx = {avg:.1f} RPS (розкид {sd:.1f}) ---", flush=True)
        offset += args.step_duration

        if args.max_g and avg >= 0.9 * args.max_g:
            print(f"[!] Досягнуто межі генератора G = {args.max_g} RPS. Зупинка.")
            break
        drops = drops + 1 if avg < 0.9 * rps else 0
        if drops >= 2:
            print("[!] Досягнута інтенсивність < 0,9 заданої на 2 сходинках поспіль. Зупинка.")
            break
        rps += args.step_increment
        step_no += 1
    else:
        print(f"[!] Вичерпано --max-steps = {args.max_steps}: сервіс не насичено, "
              f"точка N недосягнута (останній рівень {rps - args.step_increment} RPS).")


async def run_profile_mode(tl, queue, url_tpl, ids, args, summary):
    segs = []
    for part in args.profile.split(","):
        d, r = part.split(":")
        segs.append((int(d), int(r)))
    offset = 0
    for i, (dur, rps) in enumerate(segs, 1):
        print(f"\n=== ВІДРІЗОК {i}: {dur} с, {rps} RPS ===")
        await run_segment(tl, queue, url_tpl, ids, rps, dur, offset, i)
        avg, sd = avg_2xx(tl, offset, dur, skip=0)
        summary.append((i, rps, avg, sd, offset, dur))
        offset += dur


def print_summary(tl, args, summary):
    if not summary:
        return
    print("\n================ ПІДСУМОК ================")
    if args.mode == "step":
        print("Сходинка | Target | 2xx RPS (останні 20 с) | розкид | % виконання")
        for n, t, a, sd, _ in summary:
            print(f"  #{n:2d}    | {t:6d} | {a:12.1f}           | {sd:6.1f} | {a / t:7.1%}")
        best = max(summary, key=lambda x: x[2])
        n, t, a, sd, off = best
        pods = pod_avgs(tl, off, args.step_duration)
        print(f"\nНайкраща сходинка #{n}: X = {a:.1f} RPS (розкид {sd:.1f}, pstdev посекундних 2xx)")
        t0 = tl.start_epoch + off + EVAL_SKIP
        t1 = tl.start_epoch + off + args.step_duration
        print(f"   Вікно оцінки (unix): {t0:.3f} .. {t1:.3f}  <- для запитів у Prometheus")
        pooled, mean_ps = window_p99(tl, off, args.step_duration)
        print(f"   p99 клієнта: {pooled*1000:.1f} ms (об'єднана вибірка вікна), "
              f"{mean_ps*1000:.1f} ms (середнє посекундних p99)")
        if pods:
            n_pods = args.replicas or len(pods)
            if args.replicas and len(pods) < args.replicas:
                print(f"   [!] Відповіді отримали лише {len(pods)} з {args.replicas} подів; "
                      f"решта враховані з 0 RPS")
            mx, avg = max(pods.values()), sum(pods.values()) / n_pods
            for p, v in sorted(pods.items()):
                print(f"   {p}: {v:.1f} RPS")
            print(f"   I = X_max / X_avg = {mx:.1f} / {avg:.1f} = {mx / avg:.3f}  (N = {n_pods})")
    else:
        print("Відрізок | Target | 2xx RPS (середнє за відрізок)")
        for n, t, a, sd, *_ in summary:
            print(f"  #{n:2d}    | {t:6d} | {a:10.1f}")


async def main(args):
    tl = Timeline()
    summary = []
    n_conns = 8 * args.replicas_max
    queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async with aiohttp.ClientSession() as seed_session:
        ids = await seed_ids(seed_session) if "{id}" in args.endpoint else []
    url_tpl = BASE_URL + args.endpoint

    print(f"[*] Модель з'єднань: 8 * R = 8 * {args.replicas_max} = {n_conns} постійних "
          f"з'єднань, закриття після {REQS_PER_CONN} запитів")
    tl.start = time.perf_counter()
    tl.start_epoch = time.time()
    print(f"[*] Початок прогону (unix): {tl.start_epoch:.3f}")

    workers = [asyncio.create_task(connection_worker(queue, tl, stop_event))
               for _ in range(n_conns)]
    rep = asyncio.create_task(reporter(tl))
    try:
        if args.mode == "step":
            await run_step_mode(tl, queue, url_tpl, ids, args, summary)
        else:
            await run_profile_mode(tl, queue, url_tpl, ids, args, summary)
        await asyncio.sleep(1.0)  # дати завершитися запитам, що ще виконуються
    finally:
        stop_event.set()
        rep.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        flush_remaining(tl)
        save_csv(tl, args.csv)
        print_summary(tl, args, summary)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["step", "profile"], default="step")
    ap.add_argument("--replicas-max", type=int, default=5, help="R за варіантом (8*R з'єднань)")
    ap.add_argument("--endpoint", default="/implants/{id}")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--csv", default="load_results.csv")
    # режим step
    ap.add_argument("--warmup-rps", type=int, default=200)
    ap.add_argument("--warmup-duration", type=int, default=10)
    ap.add_argument("--step-increment", type=int, default=200)
    ap.add_argument("--step-duration", type=int, default=30)
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--max-g", type=int, default=3200, help="межа генератора G з лаб. 2")
    ap.add_argument("--replicas", type=int, default=None,
                    help="N: кількість реплік у цьому прогоні (для коефіцієнта дисбалансу I)")
    # режим profile
    ap.add_argument("--profile", default=None, help='напр. "30:104,60:690,90:104"')
    cli = ap.parse_args()
    if cli.mode == "profile" and not cli.profile:
        ap.error("для --mode profile потрібен --profile")
    BASE_URL = cli.base_url.rstrip("/")
    try:
        asyncio.run(main(cli))
    except KeyboardInterrupt:
        pass