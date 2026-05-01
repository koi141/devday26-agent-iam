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
- 非機密値は `configmap.yaml` 側で管理してください（`.env` は実行経路で使用しません）。
- `deployment.yaml` の `image` は必要に応じて更新してください。
- `ingress.yaml` のホスト名・証明書OCIDは環境に合わせて変更してください。
- Chainlit UI 接続安定のため、現状は `replicas: 1` で運用しています（shared LB 環境で socket.io セッション分散を回避）。

## 移行先既定値
- namespace: `iam`
- host: `iam.devday26.sogawa-yk.com`
- 必須 ConfigMap キー:
  - `domain_url`
  - `genai_baseurl`
  - `genai_project`
  - `genai_project_id`
- 必須 Secret:
  - `iam-agent-runtime-config`
  - `domain-client-credential`
  - `oci-genai-key`
  - `iam-agent-langfuse`
