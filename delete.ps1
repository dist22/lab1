Write-Host "Видалення кластера k8s-lab3..." -ForegroundColor Yellow
kind delete cluster --name k8s-lab3
Write-Host "Кластер успішно видалено." -ForegroundColor Green