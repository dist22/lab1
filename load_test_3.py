import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor
import numpy as np

# --- НАЛАШТУВАННЯ КРОКУ 6 ---
TARGET_URL = "http://localhost:8080/noop"
TIMEOUT_SEC = 5.0

WARMUP_RPS = 500
WARMUP_SEC = 10

STEP_START_RPS = 500
STEP_INCREMENT_RPS = 500
STEP_SEC = 20
MAX_STEPS = 10  # Наприклад, до 5000 RPS


def send_single_request(url, planned_time, session):
    now = time.perf_counter()
    sleep_time = planned_time - now
    if sleep_time > 0:
        time.sleep(sleep_time)

    try:
        resp = session.get(url, timeout=TIMEOUT_SEC)
        latency = max(0.0, (time.perf_counter() - planned_time) * 1000.0)
        return latency, resp.status_code, False
    except requests.exceptions.Timeout:
        latency = max(0.0, (time.perf_counter() - planned_time) * 1000.0)
        return latency, 408, False
    except Exception:
        latency = max(0.0, (time.perf_counter() - planned_time) * 1000.0)
        return latency, 500, True


def run_step(target_rps, duration_sec):
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=max(500, target_rps),
        pool_maxsize=max(500, target_rps)
    )
    session.mount("http://", adapter)

    max_workers = max(300, target_rps + 50)
    total_2xx = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for sec in range(1, duration_sec + 1):
            sec_start_time = time.perf_counter()
            interval = 1.0 / target_rps

            futures = []
            for i in range(target_rps):
                planned_time = sec_start_time + (i * interval)
                f = executor.submit(send_single_request, TARGET_URL, planned_time, session)
                futures.append(f)

            results = [f.result() for f in futures]

            sent_count = len(results)
            # 204 No Content вважається успішною відповіддю
            code_success = sum(1 for r in results if r[1] in (200, 204))
            code_fail = sum(1 for r in results if r[1] not in (200, 204) and not r[2])
            conn_errors = sum(1 for r in results if r[2])

            latencies = [r[0] for r in results]
            p50 = np.percentile(latencies, 50) if latencies else 0.0
            p95 = np.percentile(latencies, 95) if latencies else 0.0
            p99 = np.percentile(latencies, 99) if latencies else 0.0

            print(f"[{sec:02d}s] Target: {target_rps:<4} | Sent: {sent_count:<4} | OK(204): {code_success:<4} | "
                  f"Fail: {code_fail:<4} | ConnErr: {conn_errors:<2} | "
                  f"p50: {p50:6.1f}ms | p95: {p95:6.1f}ms | p99: {p99:6.1f}ms")

            total_2xx += code_success

            elapsed = time.perf_counter() - sec_start_time
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

    return total_2xx / duration_sec


def main():
    print(f"=== ПРОГРІВ /noop ({WARMUP_SEC}с @ {WARMUP_RPS} RPS) ===")
    run_step(WARMUP_RPS, WARMUP_SEC)

    current_rps = STEP_START_RPS
    max_achieved_rps = 0

    print("\n=== ТЕСТУВАННЯ МЕЖІ ГЕНЕРАТОРА (NOOP) ===")
    for step in range(1, MAX_STEPS + 1):
        print(f"\n--- Сходинка #{step}: Задано {current_rps} RPS (Тривалість {STEP_SEC}с) ---")
        avg_achieved_rps = run_step(current_rps, STEP_SEC)

        if avg_achieved_rps > max_achieved_rps:
            max_achieved_rps = avg_achieved_rps

        ratio = avg_achieved_rps / current_rps
        print(f"--> Підсумок Сходинки #{step}: Задано={current_rps}, Досягнуто={avg_achieved_rps:.1f} RPS (Коефіцієнт: {ratio:.2f})")

        current_rps += STEP_INCREMENT_RPS

    print(f"\n🏆 МЕЖА ГЕНЕРАТОРА G = {max_achieved_rps:.1f} RPS")


if __name__ == "__main__":
    main()