"""
Ступінчасте навантаження (open-loop) з посекундним виводом результатів.
Профіль: прогрів 10 секунд, далі сходинки +200 RPS по 20 секунд. 
"""
import argparse
import asyncio
import random
import sys
import time
import uuid
from collections import defaultdict

import aiohttp
import numpy as np
import pandas as pd

BASE_URL = "http://localhost:8088"
OUTPUT_CSV = "step_load_results.csv"
TIMEOUT_SEC = 5.0
TICK = 0.01  # планування пачками по 10 мс
EVAL_SKIP = 5  # перші 5 с сходинки — перехідні

class Bucket:
    __slots__ = ("sent", "ok", "http", "timeout", "conn", "lats")

    def __init__(self):
        self.sent = self.ok = self.http = self.timeout = self.conn = 0
        self.lats = []  # затримки лише 2xx


class Timeline:
    def __init__(self):
        self.start = 0.0
        self.b = defaultdict(Bucket)
        self.target = {}
        self.step = {}
        self.printed = -1


def row_values(tl, sec):
    b = tl.b.get(sec)
    if b is None:
        b = Bucket()
    if b.lats:
        p50, p95, p99 = (float(np.percentile(b.lats, q)) for q in (50, 95, 99))
    else:
        p50 = p95 = p99 = 0.0
        
    step_raw = tl.step.get(sec, "")
    if step_raw == 0:
        step_str = "W"
    else:
        step_str = str(step_raw)
        
    return {
        "second": sec,
        "step": step_str,
        "target_rps": tl.target.get(sec, 0),
        "actual_send_rps": b.sent,
        "achieved_2xx_rps": b.ok,
        "non_2xx": b.http,
        "timeout": b.timeout,
        "conn_error": b.conn,
        "p50_sec": round(p50, 5),
        "p95_sec": round(p95, 5),
        "p99_sec": round(p99, 5)
    }


def print_row(tl, sec):
    r = row_values(tl, sec)
    bad = r["non_2xx"] or r["timeout"] or r["conn_error"]
    extra = ""
    if bad:
        extra += "  <-- ПОМИЛКИ З'ЄДНАННЯ АБО НЕ-2xx"
    
    prefix = "\033[91m" if bad else ""
    suffix = "\033[0m" if bad else ""

    print(f"{prefix}t={sec:4d}s  step={r['step']:>2}  target={r['target_rps']:6d}  "
          f"sent={r['actual_send_rps']:6d}  2xx={r['achieved_2xx_rps']:6d}  "
          f"non2xx={r['non_2xx']:5d}  tmo={r['timeout']:5d}  conn={r['conn_error']:5d}  "
          f"p50={r['p50_sec']*1000:7.1f}  p95={r['p95_sec']*1000:7.1f}  "
          f"p99={r['p99_sec']*1000:7.1f} ms{extra}{suffix}", flush=True)


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


async def one_request(session, url, sched, tl):
    sent_at = time.perf_counter()
    tl.b[int(sent_at - tl.start)].sent += 1
    kind = "conn"
    try:
        async with session.get(url) as resp:
            await resp.read()
            kind = "ok" if 200 <= resp.status < 300 else "http"
    except asyncio.TimeoutError:
        kind = "timeout"
    except Exception:
        kind = "conn"
    
    comp = time.perf_counter()
    b = tl.b[int(comp - tl.start)]
    
    if kind == "ok":
        b.ok += 1
        # ЗАХИСТ ВІД ВІД'ЄМНИХ ЗАТРИМОК (Помилка №7)
        b.lats.append(max(0.0, comp - sched))
    elif kind == "http":
        b.http += 1
    elif kind == "timeout":
        b.timeout += 1
    else:
        b.conn += 1


async def run_step(session, tl, pending, url_tpl, ids, rps, duration, offset, step_no):
    for s in range(offset, offset + duration):
        tl.target[s] = rps
        tl.step[s] = step_no
    for k in range(int(duration / TICK)):
        tick_time = tl.start + offset + k * TICK
        delay = tick_time - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            # Жорсткий захист від випередження таймера
            while time.perf_counter() < tick_time:
                pass
                
        n = int(rps * (k + 1) * TICK + 1e-9) - int(rps * k * TICK + 1e-9)
        for _ in range(n):
            url = url_tpl.format(id=random.choice(ids)) if ids else url_tpl
            t = asyncio.create_task(one_request(session, url, tick_time, tl))
            pending.add(t)
            t.add_done_callback(pending.discard)


def step_avg_2xx(tl, offset, duration):
    secs = range(offset + EVAL_SKIP, offset + duration)
    total = sum(tl.b[s].ok for s in secs if s in tl.b)
    return total / (duration - EVAL_SKIP)


async def main(args):
    tl = Timeline()
    pending = set()
    summary = []
    connector = aiohttp.TCPConnector(limit=0)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        ids = await seed_ids(session) if "{id}" in args.endpoint else []
        url_tpl = BASE_URL + args.endpoint

        tl.start = time.perf_counter()
        rep = asyncio.create_task(reporter(tl))
        
        try:
            print(f"\n{'='*55}")
            print(f"=== ПРОГРІВ ({args.warmup_duration} секунд) ===")
            print(f"{'='*55}")
            offset = 0
            await run_step(session, tl, pending, url_tpl, ids,
                           args.warmup_rps, args.warmup_duration, offset, 0)
            offset += args.warmup_duration

            rps = args.step_increment
            drops, step_no = 0, 1
            while True:
                print(f"\n{'='*55}")
                print(f"=== СХОДИНКА {step_no} (Target RPS: {rps}, Час: {args.step_duration}с) ===")
                print(f"{'='*55}")
                
                await run_step(session, tl, pending, url_tpl, ids,
                               rps, args.step_duration, offset, step_no)
                
                avg = step_avg_2xx(tl, offset, args.step_duration)
                summary.append((step_no, rps, avg))
                print(f"\n--- Підсумок сходинки {step_no}: середня 2xx RPS = {avg:.1f} ---\n", flush=True)
                offset += args.step_duration

                if args.max_g and avg >= 0.9 * args.max_g:
                    print(f"[!] Досягнуто межі генератора G ({args.max_g} RPS). Зупинка.")
                    break
                
                if avg < 0.9 * rps:
                    drops += 1
                else:
                    drops = 0
                    
                if drops >= 2:
                    break
                rps += args.step_increment
                step_no += 1

            if pending:
                await asyncio.wait(pending, timeout=TIMEOUT_SEC + 1)
        finally:
            rep.cancel()
            flush_remaining(tl)
            if tl.b or tl.target:
                last = max(list(tl.b.keys()) + list(tl.target.keys()))
                pd.DataFrame([row_values(tl, s) for s in range(last + 1)]).to_csv(
                    args.csv, index=False)
            if summary:
                print("\nПідсумок по сходинках:")
                for n, t, a in summary:
                    print(f"  #{n:2d}  target={t:6d}  achieved_2xx={a:9.1f}  ({a / t:5.1%})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="/implants/{id}")
    ap.add_argument("--warmup-rps", type=int, default=200)
    ap.add_argument("--warmup-duration", type=int, default=10)
    ap.add_argument("--step-increment", type=int, default=200)
    ap.add_argument("--step-duration", type=int, default=20)
    ap.add_argument("--max-g", type=int, default=None)
    ap.add_argument("--csv", default=OUTPUT_CSV)
    ap.add_argument("--base-url", default=BASE_URL)
    cli = ap.parse_args()
    BASE_URL = cli.base_url.rstrip("/")
    try:
        asyncio.run(main(cli))
    except KeyboardInterrupt:
        pass