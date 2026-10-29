import asyncio
import time
import random
import uuid
import numpy as np
import pandas as pd
import aiohttp

# ================= Налаштування =================
BASE_URL = "http://localhost:8080"  # Адреса Nginx або сервісу
OUTPUT_CSV = "step_load_results.csv"

# Налаштування профілю (Крок 5)
WARMUP_RPS = 200
WARMUP_DURATION = 10
STEP_INCREMENT = 200
STEP_DURATION = 20
TIMEOUT_SEC = 5.0
# =================================================

class LoadTestStats:
    def __init__(self):
        self.records = []  # (scheduled_t, actual_send_t, completion_t, is_2xx, is_conn_err, latency, target_rps)

    def add(self, scheduled_t, actual_send_t, completion_t, is_2xx, is_conn_err, latency, target_rps):
        self.records.append({
            'scheduled_t': scheduled_t,
            'actual_send_t': actual_send_t,
            'completion_t': completion_t,
            'is_2xx': is_2xx,
            'is_conn_err': is_conn_err,
            'latency': latency,
            'target_rps': target_rps
        })

    def export_per_second_csv(self, filename, start_time):
        if not self.records:
            return
        
        df = pd.DataFrame(self.records)
        df['sched_sec'] = (df['scheduled_t'] - start_time).astype(int)
        df['comp_sec'] = (df['completion_t'] - start_time).astype(int)
        df['send_sec'] = (df['actual_send_t'] - start_time).astype(int)

        max_sec = int(df['completion_t'].max() - start_time) + 1
        per_sec_data = []

        for sec in range(max_sec):
            # Запитані/відправлені в цю секунду
            sent_in_sec = df[df['send_sec'] == sec]
            sched_in_sec = df[df['sched_sec'] == sec]
            
            # Завершені відповіді в цю секунду
            comp_in_sec = df[df['comp_sec'] == sec]

            target_rps = sched_in_sec['target_rps'].iloc[0] if len(sched_in_sec) > 0 else 0
            actual_send_rps = len(sent_in_sec)
            
            completed_2xx = len(comp_in_sec[comp_in_sec['is_2xx'] == True])
            completed_non_2xx = len(comp_in_sec[comp_in_sec['is_2xx'] == False])
            conn_errors = len(comp_in_sec[comp_in_sec['is_conn_err'] == True])

            # Затримка рахується для запитів, запланованих у цю секунду
            latencies = sched_in_sec['latency'].values
            if len(latencies) > 0:
                p50 = np.percentile(latencies, 50)
                p95 = np.percentile(latencies, 95)
                p99 = np.percentile(latencies, 99)
            else:
                p50, p95, p99 = 0.0, 0.0, 0.0

            per_sec_data.append({
                'second': sec,
                'target_rps': target_rps,
                'actual_send_rps': actual_send_rps,
                'achieved_2xx_rps': completed_2xx,
                'non_2xx_count': completed_non_2xx,
                'conn_error_count': conn_errors,
                'p50_sec': round(p50, 5),
                'p95_sec': round(p95, 5),
                'p99_sec': round(p99, 5)
            })

        res_df = pd.DataFrame(per_sec_data)
        res_df.to_csv(filename, index=False)
        print(f"\n[+] Результати посекундного прогону збережено у {filename}")

async def seed_database_if_needed(session, base_url):
    """Автоматичний посів 100 записів для уникнення 404"""
    print("[*] Перевірка бази даних на наявність 100 записів...")
    ids = []
    try:
        async with session.get(f"{base_url}/implants?limit=100") as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("items", [])
                ids = [item["id"] for item in items]
    except Exception as e:
        print(f"[!] Помилка підключення при посіві: {e}")

    needed = 100 - len(ids)
    if needed > 0:
        print(f"[*] База містить {len(ids)} записів. Створюємо ще {needed}...")
        for _ in range(needed):
            payload = {
                "patientCode": f"PAT-{random.randint(1000, 9999)}",
                "deviceType": "Pacemaker",
                "manufacturer": "MedTech",
                "serialNumber": f"SN-{uuid.uuid4().hex[:12]}",
                "installationDate": "2026-01-01T00:00:00Z",
                "lifespanYears": 5
            }
            async with session.post(f"{base_url}/implants", json=payload) as resp:
                if resp.status in (200, 201):
                    res_data = await resp.json()
                    ids.append(res_data["id"])

    print(f"[+] Готово. Знайдено/створено {len(ids)} валідних GUIDs.")
    return ids[:100]

async def send_single_request(session, url, scheduled_time, stats, target_rps):
    actual_send_time = time.perf_counter()
    is_2xx = False
    is_conn_err = False

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEC)) as resp:
            is_2xx = (200 <= resp.status < 300)
    except asyncio.TimeoutError:
        is_2xx = False  # Тайм-аут рахується як не-2xx
    except Exception:
        is_conn_err = True
        is_2xx = False

    completion_time = time.perf_counter()
    # Затримка рахується від запланованого моменту надсилання
    latency = completion_time - scheduled_time
    stats.add(scheduled_time, actual_send_time, completion_time, is_2xx, is_conn_err, latency, target_rps)

async def run_step(session, target_url, ids, target_rps, duration, stats, test_start_time):
    print(f"\n---> Запуск сходинки: Target RPS = {target_rps}, Тривалість = {duration}s")
    interval = 1.0 / target_rps
    tasks = []
    
    step_start = time.perf_counter()
    for i in range(int(target_rps * duration)):
        scheduled_time = step_start + (i * interval)
        now = time.perf_counter()
        sleep_delay = scheduled_time - now
        if sleep_delay > 0:
            await asyncio.sleep(sleep_delay)

        # Якщо тестуємо /noop, URL не потребує ID
        url = target_url if "{id}" not in target_url else target_url.format(id=random.choice(ids))
        
        task = asyncio.create_task(send_single_request(session, url, scheduled_time, stats, target_rps))
        tasks.append(task)

    await asyncio.gather(*tasks, return_exceptions=True)

async def main(target_endpoint="/implants/{id}", max_g_limit=None):
    connector = aiohttp.TCPConnector(limit=0)  # Без обмеження розміру пулу на боці клієнта
    async with aiohttp.ClientSession(connector=connector) as session:
        ids = []
        if "{id}" in target_endpoint:
            ids = await seed_database_if_needed(session, BASE_URL)

        stats = LoadTestStats()
        full_target_url = f"{BASE_URL}{target_endpoint}"
        test_start_time = time.perf_counter()

        # 1. Прогрів (10 сек, 200 RPS)
        print("\n=== ПРОГРІВ ===")
        await run_step(session, full_target_url, ids, WARMUP_RPS, WARMUP_DURATION, stats, test_start_time)

        # 2. Ступінчасте навантаження
        current_rps = 200
        consecutive_drops = 0
        step_index = 1

        while True:
            await run_step(session, full_target_url, ids, current_rps, STEP_DURATION, stats, test_start_time)

            # Обчислення досягнутої інтенсивності за останні 15 секунд сходинки
            df = pd.DataFrame(stats.records)
            step_sched_start = test_start_time + WARMUP_DURATION + (step_index - 1) * STEP_DURATION
            eval_window_start = step_sched_start + 5  # Перші 5 с — перехідні
            eval_window_end = step_sched_start + STEP_DURATION

            window_df = df[(df['completion_t'] >= eval_window_start) & (df['completion_t'] < eval_window_end)]
            achieved_2xx_count = len(window_df[window_df['is_2xx'] == True])
            avg_achieved_rps = achieved_2xx_count / 15.0

            print(f"Сходинка {step_index} (Target: {current_rps}): Середня досягнута 2xx RPS (останні 15с) = {avg_achieved_rps:.2f}")

            # Перевірка межі G (якщо задана)
            if max_g_limit and avg_achieved_rps >= 0.9 * max_g_limit:
                print(f"[!] Досягнуто межі генератора G ({max_g_limit} RPS). Зупинка.")
                break

            # Перевірка падіння досягнутої інтенсивності нижче 0.9 від заданої
            if avg_achieved_rps < 0.9 * current_rps:
                consecutive_drops += 1
                print(f"[!] Попередження: Досягнута інтенсивність ({avg_achieved_rps:.2f}) < 0.9 * Target ({current_rps}). Дроп #{consecutive_drops}")
            else:
                consecutive_drops = 0

            if consecutive_drops >= 2:
                print("[!] Зупинка: Досягнута інтенсивність нижча за 0.9 від заданої на двох сходинках поспіль.")
                break

            current_rps += STEP_INCREMENT
            step_index += 1

        stats.export_per_second_csv(OUTPUT_CSV, test_start_time)

if __name__ == "__main__":
    # Для Кроку 6: asyncio.run(main(target_endpoint="/noop"))
    # Для Кроку 7: asyncio.run(main(target_endpoint="/implants/{id}"))
    asyncio.run(main(target_endpoint="/implants/{id}"))