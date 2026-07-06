# BR_20260706: gpss_download_patent_pdf 內部 unpack 崩潰（not enough values to unpack）

## 現象（含硬證據）
2026-07-06 前案檢索 v3 任務中，對缺代表圖的核心專利呼叫 `gpss_download_patent_pdf`：

```
CN120932368A    MISS {"success": false, "error": "GPSS PDF download exception: not enough values to unpack (expected 4, got 3)"}
US20250275686A1 MISS {"success": false, "error": "GPSS PDF download exception: not enough values to unpack (expected 4, got 3)"}
CN120564339A    MISS {"success": false, "error": "GPSS PDF download exception: not enough values to unpack (expected 4, got 3)"}
```

同批 `CN121053693A` 回的是正常 typed error（"No PDF document row matching…refusing to fall back"），
可見 unpack 崩潰不是 no-match 路徑，而是某內部 tuple 解構在特定 GPSS 回應形狀下炸掉，
Python 例外被 except 吞成字串回報 — 非 typed error envelope。

## RCA（初判）
某處 `a, b, c, d = something` 期待 4 欄，但 GPSS detail/result 列在部分案件只回 3 欄。
屬於「上游回應形狀變異未防禦」＋「exception 字串化取代 typed error_code」雙缺陷。

## 建議修復
1. 定位 gpss PDF 下載路徑中的 tuple unpack，改為長度防禦（缺欄補 None 或 fail-fast typed）。
2. 崩潰路徑改回 typed envelope（如 `GPSS_PDF_ROW_SHAPE_UNEXPECTED`），保留原始列內容供 debug。

## 影響範圍
所有走 gpss_download_patent_pdf 的批次 PDF 補圖流程；命中形狀變異的案件直接失敗且無法從錯誤訊息判斷可否重試。

## 驗證手段
對本 BR 三個公開號重跑 gpss_download_patent_pdf：應回 typed error 或成功下載，不得再出現 "not enough values to unpack"。

## 修復記錄 2026-07-06 (CLOSED)
- RCA 修正：非「GPSS 回應形狀變異」。`_gpss_iter_result_rows`（f187c55 引入）docstring 宣稱 yield 4-tuple（含 link02_href）但實際只 yield 3；消費端 `_gpss_select_harder_path` 依 docstring 做 4-way unpack → 凡結果列表非空必炸。no-match 案件因迴圈體未執行而倖存，造成「部分案件才炸」的假象。
- 修復：消費端改 3-way unpack；docstring 同步改為 3-tuple 並註記本 BR。
- 驗證（rebuild 容器後重跑 BR 三案號）：
  - CN120932368A / US20250275686A1 → typed no-match error（正確 fail-fast，GPSS 無此列）
  - CN120564339A → 成功下載 CNA-120564339A.pdf（459653 bytes）
  - "not enough values to unpack" 不再出現 ✓
