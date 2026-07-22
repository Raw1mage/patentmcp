# Tasks: patentmcp_classification-bulk-export

## 0. 決策閘(進 implementing 前)

- [x] 0.1 使用者裁決 DD-1(2026-07-07):**兩者都要** — 獨立工具 `patent_bulk_export` 為主入口 + 批次分頁邏輯抽為內部共用函式(patent_search 也能複用)

## 1. GPSS client 分頁 + 批次語義(gpss/client.py)

- [x] 1.1 `search()` 分頁迴圈化(DD-2):`num` 超單頁上限時以 `expSkip` 為游標自動翻頁,累積至 num 或某頁回空;單頁 expQty 取實測穩定值(200/500)
- [x] 1.2 批次路徑強制 `expFld=DEFAULT_FIELDS` 全欄(DD-3),不允許呼叫端縮欄
- [x] 1.3 純分類軸 condition 組裝(DD-4):ipc/cpc/uspc 至少一必填;keyword 不作 AND 收窄(忽略或 OR)
- [x] 1.4 num 硬上限(如 5000)+ 可選分頁延遲,對齊 TIPO 配額

## 2. 批次匯出入口(patents.py)

- [x] 2.1 實作獨立 `@mcp.tool() patent_bulk_export`(主入口);分頁批次核心抽為 client/dispatcher 內部共用函式,patent_search 也能複用(DD-1)
- [x] 2.2 官方 miss 不退爬蟲(DD-5):GPSS 未 configured → 明確錯誤;回 0 → 真 0 + provenance reason=zero_hits,不接來源梯尾級
- [x] 2.3 GPSS JSON → records 正規化(沿用 screening_table 欄位),輸出 records(或直接 CSV)

## 3. 落地 patentdb(DD-6)

- [x] 3.1 records → CSV → `patentdb_import_csv` 對接,確認完整 row 入庫
- [x] 3.2 確認 `put()` COALESCE-only 相容(半殘 row 回補不破壞既有欄位),預期無需改 patentdb_store.py

## 4. 單元測試(monkeypatch GPSS client,不打真網路)

- [x] 4.1 分頁迴圈:多頁累積、末頁回空停止、達 num 上限停止
- [x] 4.2 expFld 強制全欄:呼叫端無法縮欄
- [x] 4.3 miss 不退爬蟲:GPSS 回 0 → 真 0,斷言不觸發 SCRAPING_REQUIRED / 不呼叫 gpatents
- [x] 4.4 純分類軸 + 大 num:斷言 keyword 不作收窄、num 傳至 expQty
- [x] 4.5 重啟 server `GET /tools` 確認入口註冊 + schema 正確

## 5. 標準面 + 文件同步(DD-7)

- [x] 5.1 `mcp.json`:version bump + instructions 宣告「relevance search vs 分類軸批次匯出」兩語義分工
- [x] 5.2 README + `skills/patentworks/SKILL.md` §5 / priorsearch flow 補入批次匯出工具與適用時機
- [x] 5.3 附帶回補說明:306 件 title_en 空白 row 用批次匯出重抓對應軸 import_csv 補齊(文件記錄 SOP,不在本案批次執行)

## 6. 收尾

- [x] 6.1 event_record 收尾(決策/驗證/architecture sync)
- [x] 6.2 BR_20260707 標記 Resolved → 移至 issues/closed/
- [x] 6.3 plan_advance 至 verified
