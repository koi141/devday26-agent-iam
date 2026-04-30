# devday26-agent-iam Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-04-30

## Active Technologies
- Oracle Database (HR.EMPLOYEES 参照), 外部 API (Identity Domains / OCI IAM / OCI Generative AI) (001-iam-initial-tools)
- Python 3.12 + `requests`, `oci`, `oracledb`, `chainlit`, `openai` (OCI Generative AI API 利用), `pydantic`, `python-dotenv`, `pytest` (001-iam-initial-tools)
- 永続DBなし (運用ログは構造化ログとして標準出力/ファイルへ出力) (001-iam-initial-tools)
- Python 3.12 (プロジェクト要件: `>=3.12`) + `chainlit`, `oci`, `requests`, `oracledb`, `openai`, `oci-openai`, `pydantic`, `python-dotenv`, `pytest` (003-iam-access-diagnostics)
- 永続DBなし（監査ログ出力 + `knowledge/` Markdown ナレッジ蓄積） (003-iam-access-diagnostics)
- Python 3.12 (`requires-python >=3.12`) + `chainlit`, `oci`, `requests`, `oracledb`, `openai`, `oci-openai`, `pydantic`, `python-dotenv`, `pytest`, Langfuse Python SDK（追加） (004-langfuse-performance)
- Langfuse（trace/observation/score）、既存構造化監査ログ、`knowledge/` Markdown (004-langfuse-performance)
- Python 3.12 (`requires-python >=3.12`) + `chainlit`, `oci`, `requests`, `pydantic`, `python-dotenv`, `pytest`（既存の `langfuse`, `openai`, `oracledb` は回帰対象として維持） (005-add-resource-read-tools)
- OCI API 応答（永続化なし）、既存構造化監査ログ、`knowledge/` Markdown (005-add-resource-read-tools)
- Python 3.12 + `fastapi`, `chainlit`, `pydantic`, `requests`, `oci`, `pytest`, `langfuse` (006-add-a2a-support)
- 既存の構造化監査ログ、可観測性イベント、`knowledge/` Markdown（新規DB追加なし） (006-add-a2a-support)
- Python 3.12 + `fastapi`, `chainlit`, `requests`, `oci`, `oracledb`, `openai`, `pydantic`, `pytest` (007-tool-skill-refactor)

- Python 3.12 + `requests`, `oci` (OCI SDK), `oracledb`, `chainlit`, `openai` (OCI Generative AI接続), `oci-openai`/`oci-genai-auth` (001-iam-initial-tools)

## Project Structure

```text
backend/
frontend/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.12: Follow standard conventions

## Recent Changes
- 007-tool-skill-refactor: Added Python 3.12 + `fastapi`, `chainlit`, `requests`, `oci`, `oracledb`, `openai`, `pydantic`, `pytest`
- 006-add-a2a-support: Added Python 3.12 + `fastapi`, `chainlit`, `pydantic`, `requests`, `oci`, `pytest`, `langfuse`
- 005-add-resource-read-tools: Added Python 3.12 (`requires-python >=3.12`) + `chainlit`, `oci`, `requests`, `pydantic`, `python-dotenv`, `pytest`（既存の `langfuse`, `openai`, `oracledb` は回帰対象として維持）


<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
