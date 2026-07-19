# Handoff: patentmcp_gpss4-number-query-adv-route

## Execution Contract

- 交付：GPSS4 登入模式 number-query 的號碼→專利號解析改走 adv_search 路徑（能 render
  專利號）；per-session DB scope 前置 routine；§4A in-memory login gate。
- Done 定義：單元測試（scope 推導 + gate 互斥）全綠；live roundtrip（known-item +
  CN/US 跨國）抽得到公開公告號；`gpss4_resolve_appnos` 對 pending_tw_99 resolved 率
  從 0 回升；container 重啟 smoke 通過；BR_20260719 §4/§4A 標 resolved。

## Required Reads

- `issues/BR_20260719_gpss4_folder_search_missing_dbscope_and_output_field_activation.md`
- `plans/patentmcp_gpss4-number-query-adv-route/design.md`（DD-1~DD-7）
- `src/patent_mcp_server/gpss4/adv_search.py`（`harvest` / `_submit_query` /
  `_enter_dual_view` / `set_search_databases`）
- `src/patent_mcp_server/gpss4/session.py`（`GPSS4Session`）
- `src/patent_mcp_server/gpss4/folder.py`（退役對象）
- `src/patent_mcp_server/patents.py`（`gpss4_resolve_appnos` 5645 等進入點）

## Stop Gates In Force

- **live 登入前**：GPSS4 登入有帳號鎖定風險（BR §4A 血淚）；任何 live roundtrip /
  batch 驗證需使用者指定額度窗口才執行（decision gate）。
- **container 重啟**：改 code 後需重啟 patentmcp container 載入（非破壞性，但需執行）。
- **architecture_change**：number-query 路徑重定向屬架構變更，實作前 design 須定稿。

## Execution-Ready Checklist

- [x] recon 已坐實 root cause（folder 不 render 專利號、adv 路徑可）
- [x] proposal.md / design.md / idef0.json / grafcet.json 已定稿
- [x] tasks.md 已展開
- [ ] 使用者指定 live 驗證額度窗口（實作可先行，驗證待窗口）
