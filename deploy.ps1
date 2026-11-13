$ErrorActionPreference = "Stop"

function Check {
    if ($LASTEXITCODE -ne 0) { throw "Команда завершилась з кодом $LASTEXITCODE" }
}

Write-Host "1. Створення кластера..." -ForegroundColor Cyan
kind create cluster --name k8s-lab3 --config kind-config.yaml; Check

Write-Host "2. Додавання мітки role=infra на control-plane..." -ForegroundColor Cyan
kubectl label nodes k8s-lab3-control-plane role=infra; Check

Write-Host "3. Збірка Docker-образу сервісу web..." -ForegroundColor Cyan
docker build -t web:latest -f ImplantsService/Dockerfile . ; Check

Write-Host "4. Завантаження образу в kind-кластер..." -ForegroundColor Cyan
kind load docker-image web:latest --name k8s-lab3; Check

Write-Host "5. Secret і ConfigMap зі схемою..." -ForegroundColor Cyan
kubectl create secret generic postgres-secret --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -; Check
kubectl create configmap db-schema --from-file=schema.sql=ImplantsService/schema.sql --dry-run=client -o yaml | kubectl apply -f -; Check

Write-Host "6. PostgreSQL..." -ForegroundColor Cyan
kubectl apply -f k8s/postgres.yaml; Check
kubectl rollout status statefulset/postgres --timeout=180s; Check

Write-Host "7. Міграція схеми..." -ForegroundColor Cyan
kubectl delete job db-migrate --ignore-not-found; Check
kubectl apply -f k8s/migrate-job.yaml; Check
kubectl wait --for=condition=complete job/db-migrate --timeout=120s; Check

Write-Host "8. Розгортання застосунку та моніторингу..." -ForegroundColor Cyan
kubectl apply -f k8s/web.yaml; Check
kubectl apply -f k8s/monitoring.yaml; Check
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.1/components.yaml; Check
Set-Content -Path "metrics-patch.json" -Value '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
kubectl patch -n kube-system deployment metrics-server --type=json --patch-file metrics-patch.json; Check
Remove-Item "metrics-patch.json"

Write-Host "9. Розгортання Metrics Server..." -ForegroundColor Cyan
kubectl apply -f k8s/metrics-server.yaml; Check

Write-Host "10. Розгортання Prometheus та Exporters..." -ForegroundColor Cyan
kubectl apply -f k8s/monitoring.yaml; Check
kubectl rollout status deployment/prometheus --timeout=120s; Check

Write-Host "Готово! Кластер розгорнуто." -ForegroundColor Green