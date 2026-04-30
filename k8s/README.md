# Kubernetes Manifest (iam-agent)

このディレクトリは `iam-agent` の OKE デプロイ用マニフェスト配置先です。

## ファイル
- `configmap.yaml`: 非機密な環境変数
- `deployment.yaml`: アプリ本体
- `service.yaml`: ClusterIP Service
- `ingress.yaml`: OCI Native Ingress
- `manifest.generated.yaml`: `kubectl kustomize k8s` で生成した統合 manifest

## 適用
```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
# または
kubectl apply -k k8s
```

## 注意
- Secret 本体は含めていません。事前に対象Secretを作成してください。
- 非機密値は `configmap.yaml` 側で管理してください。
- `deployment.yaml` の `image` は必要に応じて更新してください。
- `ingress.yaml` のホスト名・証明書OCIDは環境に合わせて変更してください。
