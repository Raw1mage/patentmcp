# Handoff: patentmcp_cross-db-pubno-converter

## Execution Contract

執行者須交付：`src/patent_mcp_server/pubno_convert.py`（純函式 SSOT，4+2 個 `to_*` 函式）+ 5 處散點改走本 layer
+ 純函式 pytest 全覆蓋 + vendor-drift guard + `canonical_pubno` 向後相容回歸測試。
「done」定義：tasks.md 全 `[x]`、pytest 綠、少量實查 roundtrip 抽樣命中、BR_20260719 收編臨時補丁。

## Required Reads

- `issues/BR_20260719_cross_db_pubno_format_converter_layer.md`（需求 + §2.1/§2.3 已坐實證據）
- 本包 `proposal.md` / `design.md`（DD-1..5、mapping 知識表）
- `src/patent_mcp_server/epo/client.py:27,45`、`patentdb_store.py:82,109`、`patents.py:1003,1267`
- `scripts/family_backfill_offline.py:43`、`skills/patentworks/scripts/patentdb_local.py:62,89`

## Stop Gates In Force

- **實查 roundtrip（3.4）需先確認 GPSS4 下班時段 + EPO OPS 週額度**——執行前報告預估額度消耗取得同意（額度硬閘）。
- **`canonical_pubno` 行為漂移**是硬閘：回歸測試任一 fail 即停，不得繼續。

## Execution-Ready Checklist

- [x] 落點策略經使用者確認（DD-1：src 正典 + host vendor 同步）
- [x] 驗證深度經使用者確認（純函式測試 + 少量實查抽樣）
- [x] §2.1/§2.3 mapping 證據已坐實（無需重驗）
