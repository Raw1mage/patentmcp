# Handoff: mcp_r16-domain-kb

## Execution Contract

- 依 mcp-integration-standard R16 為 patentmcp 實作 in-band domain-KB 查詢工具。
- Done 定義：`patentmcp_kb_query`/`patentmcp_kb_get` 由 MCP rail 可用且唯讀；KB 缺失 fail-fast（`KB_UNAVAILABLE` envelope）；matchMode 自述；signpost 三軌就位；新測試全綠、既有套件無回歸；兩門一致性驗證通過。

## Required Reads

- `/home/pkcs12/projects/opencode/specs/mcp-integration-standard/standard.md` §R16（條文）+ §13 checklist R16.1/16.3/16.4/16.5/16.7
- `/home/pkcs12/projects/bodesign/services/mcp/server.py` L789-957（reference impl，查詢核心照抄）
- `/home/pkcs12/projects/bodesign/plans/mcp_r16-domain-kb/`（reference plan package）
- 本 repo `.specbase/ragbase.sqlite`（21 筆 corpus；known-good id：`concept.gpss.api_specification`）
- 本 repo `plans/mcp_r16-domain-kb/design.md`（DD-1..DD-6）

## Stop Gates In Force

- 容器 rebuild/restart 前如影響使用中 session，先向使用者確認時機
- `plan_graduate` 為 user-only gate，AI 不自行呼叫

## Execution-Ready Checklist

- [x] corpus 非空（21 筆，R16.1 非 ceremony）
- [x] reference impl 已 verified（bodesign）
- [x] ragbase schema 已 `.schema` 對齊（DD-2）
- [x] 錯誤面慣例已定（patentmcp envelope，DD-1）
