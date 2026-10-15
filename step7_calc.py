import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor

TARGET_URL = "http://localhost:8080/implants"
TEST_SEC = 15

# Отримуємо ID для тесту
r = requests.get(TARGET_URL)
data = r.json()
items = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
sample_id = items[0].get("id") or items[0].get("Id")
url = f"{TARGET_URL}/{sample_id}"

print("=== 1. Перевірка закону Літтла (Відкритий контур, 100 RPS) ===")
# За законом Літтла: L = lambda * W
target_rps = 100
total_requests = target_rps * TEST_SEC
interval = 1.0 / target_rps

active_requests = 0
l_samples = []
lock = threading.Lock()
latencies = []

def send_open_loop(offset):
    global active_requests
    time.sleep(offset)
    
    with lock:
        active_requests += 1
        
    start_t = time.perf_counter()
    try:
        requests.get(url, timeout=5)
    except:
        pass
    w_time = time.perf_counter() - start_t
    latencies.append(w_time)
    
    with lock:
        active_requests -= 1

def sample_l():
    for _ in range(TEST_SEC * 10):
        time.sleep(0.1)
        with lock:
            l_samples.append(active_requests)

# Запускаємо семплер L
threading.Thread(target=sample_l, daemon=True).start()

# Запускаємо запити
start_time = time.perf_counter()
with ThreadPoolExecutor(max_workers=200) as ex:
    for i in range(total_requests):
        ex.submit(send_open_loop, i * interval)

avg_W = sum(latencies) / len(latencies)
achieved_lambda = len(latencies) / TEST_SEC
calc_L = achieved_lambda * avg_W
measured_L = sum(l_samples) / len(l_samples) if l_samples else 0

print(f"Лямбда (інтенсивність): {achieved_lambda:.2f} рек/с")
print(f"W (сер. час відповіді): {avg_W:.4f} с")
print(f"Теоретичне L (Лямбда * W): {calc_L:.2f}")
print(f"Виміряне L (середня кількість активних): {measured_L:.2f}")
diff = abs(calc_L - measured_L) / calc_L * 100
print(f"Розбіжність: {diff:.2f}%\n")

print("=== 2. Порівняння із закритим контуром (на межі 500 RPS) ===")
concurrency = 150
print(f"Запускаємо закритий контур із {concurrency} одночасними потоками на {TEST_SEC} секунд...")

closed_latencies = []
stop_flag = False

def send_closed_loop():
    while not stop_flag:
        start_t = time.perf_counter()
        try:
            requests.get(url, timeout=5)
        except:
            pass
        closed_latencies.append((time.perf_counter() - start_t) * 1000)

threads = []
for _ in range(concurrency):
    t = threading.Thread(target=send_closed_loop)
    t.start()
    threads.append(t)

time.sleep(TEST_SEC)
stop_flag = True
for t in threads:
    t.join()

closed_achieved_rps = len(closed_latencies) / TEST_SEC
closed_latencies.sort()
closed_p95 = closed_latencies[int(len(closed_latencies) * 0.95)] if closed_latencies else 0

print(f"Відкритий контур (на 500 RPS, з минулого тесту): Досягнуто ~500 RPS, p95 ~ 35.59 мс (але з >60% Fail таймаутів)")
print(f"Закритий контур (Concurrency={concurrency}): Досягнуто {closed_achieved_rps:.2f} RPS, p95 = {closed_p95:.2f} мс")