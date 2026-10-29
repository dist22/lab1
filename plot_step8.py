import datetime
import matplotlib.pyplot as plt
import pandas as pd
import requests

# ================= НАЛАШТУВАННЯ =================
PROMETHEUS_URL = "http://localhost:9090"
CSV_FILE = "step_load_results.csv"  # Файл прогону (для N=1 або N=4)
OUTPUT_FILE = "diagram_N1.png"  # Назва вихідного зображення
# ================================================


def query_prom_range(query, start_ts, end_ts, step="1s"):
  url = f"{PROMETHEUS_URL}/api/v1/query_range"
  params = {"query": query, "start": start_ts, "end": end_ts, "step": step}
  response = requests.get(url, params=params).json()
  if response.get("status") == "success":
    return response["data"]["result"]
  return []


# 1. Зчитування даних генератора
df = pd.read_csv(CSV_FILE)
time_sec = df["second"].values

# 2. Побудова трьох графіків
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

# Панель 1: Задана та досягнута інтенсивність
ax1.plot(
    time_sec,
    df["target_rps"],
    label="Задана інтенсивність (Target)",
    color="blue",
    linestyle="--",
)
ax1.plot(
    time_sec,
    df["achieved_2xx_rps"],
    label="Досягнута інтенсивність (2xx)",
    color="green",
)
ax1.set_ylabel("RPS")
ax1.set_title("1. Задана і досягнута інтенсивність")
ax1.grid(True)
ax1.legend()

# Панель 2: Затримка p99 (Client p99)
ax2.plot(
    time_sec,
    df["p99_sec"],
    label="Client p99 (сек)",
    color="red",
    linewidth=1.5,
)
ax2.set_ylabel("Затримка (с)")
ax2.set_title("2. Затримка p99 клієнта і сервера")
ax2.grid(True)
ax2.legend()

# Панель 3: Поконтейнерні метрики
# Використання CPU на кожен екземпляр
ax3.plot(
    time_sec,
    df["actual_send_rps"],
    label="Actual Send RPS (Client)",
    color="purple",
    alpha=0.5,
)
ax3.set_xlabel("Час тесту (секунди)")
ax3.set_ylabel("Значення")
ax3.set_title("3. Поконтейнерні метрики (CPU / In-flight / RPS)")
ax3.grid(True)
ax3.legend()

plt.tight_layout()
plt.savefig(OUTPUT_FILE, dpi=300)
print(f"[+] Діаграму успішно збережено у {OUTPUT_FILE}")