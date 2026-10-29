import matplotlib.pyplot as plt
import numpy as np

# Виміряні значення та розкид
X_meas = {1: 141.80, 2: 169.87, 3: 170.00, 4: 141.33}
std_meas = {1: 28.50, 2: 31.20, 3: 32.10, 4: 34.21}

lambda_val = X_meas[1]
sigma = 0.1811
kappa = 0.2036

N_continuous = np.linspace(1, 4.5, 100)
X_usl = (lambda_val * N_continuous) / (
    1 + sigma * (N_continuous - 1) + kappa * N_continuous * (N_continuous - 1)
)
X_linear = lambda_val * N_continuous

N_dots = np.array([1, 2, 3, 4])
X_dots = np.array([X_meas[n] for n in N_dots])
yerr_dots = np.array([std_meas[n] for n in N_dots])

plt.figure(figsize=(8, 5))
plt.errorbar(
    N_dots,
    X_dots,
    yerr=yerr_dots,
    fmt='o',
    color='red',
    ecolor='red',
    capsize=5,
    label='Виміряні X(N) з розкидом',
)
plt.plot(
    N_continuous,
    X_usl,
    'b-',
    label=f'Універсальний закон (σ={sigma:.4f}, κ={kappa:.4f})',
)
plt.plot(
    N_continuous,
    X_linear,
    'g--',
    label=f'Лінійне масштабування λN (λ={lambda_val:.2f})',
)
plt.axvline(x=2.01, color='orange', linestyle=':', label='Максимум N* ≈ 2')

plt.xlabel('Кількість екземплярів N')
plt.ylabel('Пропускна здатність X(N), req/s')
plt.title('Крок 10. Модель Універсального закону масштабованості (USL)')
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.savefig('usl_chart.png', dpi=300)