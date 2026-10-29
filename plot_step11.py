import matplotlib.pyplot as plt

target_rps = [200, 400]

throttling_n1 = [0.0, 0.0]
throttling_n4_web1 = [0.0, 0.0]
throttling_n4_web2 = [0.0, 0.0]
throttling_n4_web3 = [0.0, 0.0]
throttling_n4_web4 = [0.0, 0.0]

plt.figure(figsize=(8, 5))
plt.plot(target_rps, throttling_n1, 'o-', label='N=1 (web-1)')
plt.plot(target_rps, throttling_n4_web1, 's--', label='N=4 (web-1)')
plt.plot(target_rps, throttling_n4_web2, '^--', label='N=4 (web-2)')
plt.plot(target_rps, throttling_n4_web3, 'v--', label='N=4 (web-3)')
plt.plot(target_rps, throttling_n4_web4, 'd--', label='N=4 (web-4)')

plt.xlabel('Задана інтенсивність (Target RPS)')
plt.ylabel('Частка дроселювання CPU (Δnr_throttled / Δnr_periods)')
plt.title(
    'Крок 11. Залежність частки дроселювання CPU від заданої інтенсивності'
    ' (Метрика М3)'
)
plt.ylim(-0.05, 0.1)
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.savefig('metric_m3_chart.png', dpi=300)