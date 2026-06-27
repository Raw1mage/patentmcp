# Proposal: analysis_batch-assets

## Why

- **痛點**：
  1. 在前案檢索工作中，專案端需要手動或撰寫 Python 腳本（如 `build_charts.py`）對專利池進行國別、年份、CPC分佈等統計，並使用 Matplotlib 繪製統計圖表，重複性高且費時。
  2. 下載專利代表圖時，單純的 URL 下載程式在遭遇 Google Patents 的 503 (Service Unavailable) 限流阻斷時會崩潰，需設計 fail-safe 跳過與快取機制。
  3. `patent_get_claim1` 目前有 1000 個字元的截斷限制，容易遺漏後半段的權利要求原文，影響法規分析的完整度。
- **機會**：將「專利池自動分析與圖表生成」、「防限流批次代表圖下載」與「完整 Claim 1 原文撈取」做為原生工具下沉到 `patentmcp` 中，徹底消滅本地自製爬網與繪圖腳本。

## Original Requirement Wording (Baseline)

- "請盤點現在自製的所有腳本，哪些是值得納入 patentmcp 或 docxmcp 中成為可重用的工具？發 plan 給對應的 repo 來開發處理。"

## Requirement Revision History

- 2026-06-26: initial draft created via plan-init.ts
- 2026-06-26: Detailed proposal written to define pool analysis and batch asset retrieval.

## Effective Requirement Description

優化並擴充 `patentmcp` 工具集，實現專利池統計分析、防 503 限流批次下載與完整 Claim 撈取。

## Scope

### IN
1. **優化 `patent_get_claim1`**：
   - 新增 `full` 參數（布林值，預設為 `True`）。
   - 當 `full=True` 時，返回完整、未截斷的 Claim 1 原文。
2. **新增 `patentmcp_batch_download_figures`**：
   - **輸入**：`publication_numbers`（專利號清單）、`output_dir`（本地圖片輸出目錄）、`cache_path`（下載快取與 503 失敗記錄路徑）。
   - **邏輯**：逐一檢查本地圖片是否已存在。若不存在，由 `raw_patents` 或 `gpatents_search` 獲取 URL 下載。若遭遇 503 阻斷，自動觸發非同步冷卻，將失敗專利標記至快取 JSON 並安全跳過，防編譯鏈中斷。
3. **新增 `patentmcp_analyze_pool`**：
   - **輸入**：`publication_numbers`（專利號清單）、`output_dir`（圖表輸出目錄）。
   - **邏輯**：自動撈取清單內所有專利號的國別、公開年份、CPC Top 10 與 Scenario 分佈。生成並繪製 5 張標準統計圖表（n=清單長度），存入 `output_dir`。

### OUT
- 不提供非專利文獻的圖表統計。
- 統計圖表之配色與主題採固定高質感 HSL 模板，不提供複雜的 ad-hoc 自訂繪圖參數。

## Non-Goals

- 本工具不提供除了標準前案分析圖表（國別、相關性、CPC、類別、年份）以外的自訂圖表繪製。

## Constraints

- 專利號清單上限為 200 件。

## What Changes

- 優化 `patent_get_claim1.py` 處理邏輯。
- 新增 `patentmcp_batch_download_figures.py` 與 `patentmcp_analyze_pool.py` 原生 MCP 工具。

## Capabilities

### New Capabilities
- `patentmcp_batch_download_figures`: 防限流專利代表圖批次下載器。
- `patentmcp_analyze_pool`: 專利池全局統計分析與圖表生成器。

### Modified Capabilities
- `patent_get_claim1`: 提供無截斷的完整 Claim 1 原文。

## Impact

- 擴充 `patentmcp` 的工具庫與接口，提昇前案檢索流程自動化程度。
