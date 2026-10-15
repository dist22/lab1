import time
import statistics
import requests
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import os

TARGET_URL = "http://localhost:8080/implants"
WARMUP_SEC = 10
TEST_SEC = 30
RPS_LEVELS = [10, 100, 500]
RUNS_PER_LEVEL = 3

def send_request(url, start_time, target_offset):
    now = time.perf_counter()
    sleep_time = (start_time + target_offset) - now
    if sleep_time > 0:
        time.sleep(sleep_time)
    
    req_start = time.perf_counter()
    try:
        resp = requests.get(url, timeout=5)
        latency = (time.perf_counter() - req_start) * 1000 # мс
        return latency, resp.status_code
    except Exception:
        return (time.perf_counter() - req_start) * 1000, 500

def run_worker(target_rps, duration, sample_id, num_workers, worker_id):
    worker_rps = target_rps / num_workers
    interval = 1.0 / worker_rps
    total_requests = int(worker_rps * duration)
    url = f"{TARGET_URL}/{sample_id}"
    
    results = []
    start_time = time.perf_counter()
    
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = []
        for i in range(total_requests):
            offset = i * interval
            f = executor.submit(send_request, url, start_time, offset)
            futures.append(f)
            
        for f in futures:
            results.append(f.result())
            
    return results

def run_test(target_rps, duration, sample_id):
    num_workers = max(1, os.cpu_count() - 1)
    
    # Прогрів (Warmup)
    print(f"  Прогрів {WARMUP_SEC}с...")
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(run_worker, target_rps, WARMUP_SEC, sample_id, num_workers, i)
            for i in range(num_workers)
        ]
        for f in futures:
            f.result()
            
    # Основний замір (Measurement)
    print(f"  Тест {duration}с під {target_rps} RPS...")
    all_results = []
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(run_worker, target_rps, duration, sample_id, num_workers, i)
            for i in range(num_workers)
        ]
        for f in futures:
            all_results.extend(f.result())
            
    latencies = [r[0] for r in all_results]
    status_codes = [r[1] for r in all_results]
    
    achieved_rps = len(latencies) / duration
    non_2xx_ratio = sum(1 for code in status_codes if not (200 <= code < 300)) / len(status_codes)
    
    latencies.sort()
    p50 = statistics.quantiles(latencies, n=100)[49]
    p95 = statistics.quantiles(latencies, n=100)[94]
    p99 = statistics.quantiles(latencies, n=100)[98]
    
    return {
        "target_rps": target_rps,
        "achieved_rps": round(achieved_rps, 2),
        "p50": round(p50, 2),
        "p95": round(p95, 2),
        "p99": round(p99, 2),
        "non_2xx": round(non_2xx_ratio, 4)
    }

if __name__ == "__main__":
    print("Отримання записів для тестування...")
    r = requests.get(TARGET_URL)
    response_data = r.json()
    
    if isinstance(response_data, list):
        items_list = response_data
    elif isinstance(response_data, dict):
        items_list = next((v for v in response_data.values() if isinstance(v, list)), [])
    else:
        items_list = []
    
    if len(items_list) < 100:
        print(f"В базі знайдено лише {len(items_list)} записів. Доповнюємо до 100...")
        for i in range(100 - len(items_list)):
            payload = {
                "patientCode": f"PAT-{i}",
                "deviceType": "Stent",
                "manufacturer": "MedTech",
                "serialNumber": f"SN-{time.time_ns()}-{i}",
                "installationDate": "2026-01-01T00:00:00Z",
                "lifespanYears": 10
            }
            post_r = requests.post(TARGET_URL, json=payload)
            if post_r.status_code != 201:
                print(f"Помилка створення запису {i}: {post_r.status_code} - {post_r.text}")
        
        r = requests.get(TARGET_URL)
        response_data = r.json()
        if isinstance(response_data, list):
            items_list = response_data
        elif isinstance(response_data, dict):
            items_list = next((v for v in response_data.values() if isinstance(v, list)), [])

    if not items_list:
        raise ValueError("Список записів порожній!")

    sample_id = items_list[0].get("id") or items_list[0].get("Id")
    print(f"Успішно! Тестуємо на ID: {sample_id}\n")
    
    for rps in RPS_LEVELS:
        print(f"=== Рівень {rps} RPS ===")
        runs = []
        for run in range(RUNS_PER_LEVEL):
            print(f"Запуск #{run + 1}:")
            res = run_test(rps, TEST_SEC, sample_id)
            runs.append(res)
            print(f"  Отримано: {res['achieved_rps']} RPS | p50: {res['p50']}ms | p95: {res['p95']}ms | p99: {res['p99']}ms | Fail: {res['non_2xx']*100}%")
            time.sleep(2)
            
        runs.sort(key=lambda x: x["p50"])
        median_run = runs[1]
        print(f"-> МЕДІАНА для {rps} RPS: Achieved={median_run['achieved_rps']} RPS, p50={median_run['p50']}ms, p95={median_run['p95']}ms, p99={median_run['p99']}ms, Fail={median_run['non_2xx']*100}%\n")