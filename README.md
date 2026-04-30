# devday26-agent-iam

OCI IAM / Identity Domains の運用支援エージェントです。

## できること
- Identity Domains: `list_users`, `get_user`, `create_user`, `list_groups`, `get_group`, `add_user_to_group`, `remove_user_from_group`, `list_user_credentials`, `get_last_successful_login`
- OCI IAM: `list_compartments`, `list_resources`, `list_policies`, `get_policy`
- HR DB: `query_hr_database`（ユーザー特定/補完）
- 複合ワークフロー: 権限調査、アクセス拒否トラブルシュート、A2A 連携

## アーキテクチャ（要約）
- atomic tool: `src/iam_agent/tools/` 配下
- skill: `src/iam_agent/skills/` 配下
- 互換レイヤー: `src/iam_agent/tools/*.py`（既存外部契約維持）

## ローカル実行
```bash
uv sync
PYTHONPATH=src uv run uvicorn iam_agent.api.orch_routes:app --host 0.0.0.0 --port 8000
```

## テスト
```bash
PYTHONPATH=src uv run pytest -q
```

## 注意
- シークレットやトークン本文はログ/応答に表示しない設計です。
- 高リスク操作（作成/所属変更など）は監査対象として扱います。
