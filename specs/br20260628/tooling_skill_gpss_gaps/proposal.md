# Proposal: br20260628_tooling_skill_gpss_gaps

## Why

2026-06-28 一次 priorsearch session(iSafe2.0 R2)暴露三份 BR,共 ~9 個可修點,
散落在 patentmcp 工具層與 patentworks skill 文件。核心病灶有三:

1. **工具靜默走爬蟲**:`fetch_patent_pdf` 描述寫「Routes official sources first」,
   實測對三件案全部 fallback 到 GPSS headless 爬蟲,唯一爬蟲訊號藏在事後 `provenance.scraping`,
   讓 §5「爬蟲需明確同意」天條形同虛設。
2. **AI 來源梯未窮舉即宣告無解**:同一 session 被使用者連續四次糾正——claim/圖/全文
   在第①級回空就停手,不走 PPUBS/PDF fallback。skill §5 沒有硬規則要求「宣告缺失前逐級走完來源梯」。
3. **GPSS 既知缺口**:US 案 claim1 回空無旗標、無 uspc 軸、無 INPADOC family ID。

## Original Requirement Wording (Baseline)

- "處理新發的 BR" → 經確認為 2026-06-28 三份新 BR,使用者選擇「開 plan-builder spec 統籌全部」。

## Requirement Revision History

- 2026-06-28: initial draft created via plan-init.ts
- 2026-06-28: 範圍鎖定三份 BR;BR① A(工具未 surface)移出範圍(屬 opencode side)。

## Effective Requirement Description

統籌修復三份 BR 中所有「本 repo 可改」的點,跨 code(工具層 + gpss)與 skill 文件,
逐項實作 + 驗證,並對需先查規格的點(uspc/family)做偵查後決策。

## Capabilities

- 工具層顯式爬蟲 gate（`fetch_patent_pdf allow_scraping`）+ 參數命名統一（`publication_number(s)` canonical + alias）
- `extract_representative_figure` 失敗分級 + `ppubs_get_full_document` 便利包裝
- GPSS `claim1_empty` 旗標（US 案空 claim1 偵測）
- patentworks SKILL.md §5 來源梯窮舉門檻 + 工具清單更新 + 爬蟲天條重寫
- D1/D2 偵查後決策（USPC 軸 / INPADOC family 落 skill 文件記載）

## Scope

### IN

**A. 工具層 code(BR③)**
- A1: `fetch_patent_pdf` 加 `allow_scraping: bool = False`;預設 False 時,官方來源(epo_images/google_citation/local_cache)miss 後,**不靜默走 gpss_pdf 爬蟲**,改回明確「需授權」結果(含 attempts trace)。
- A2: 取圖/取文工具家族參數命名統一為 `publication_number`(單)/ `publication_numbers`(複);舊名 `patent_number`/`patent_numbers` 保留為 alias 不破壞既有呼叫。
- A3: `extract_representative_figure` 失敗分級:有文字層→找 FIG.1;無文字層但有 image XObject→回影像清單 + 頁碼供挑選(非一律 `NO_FIGURE_PAGE`);真無影像才 `NO_FIGURE_PAGE`。
- A4: `ppubs_get_full_document` 加 `publication_number` 便利包裝,內部自動 pub number → PPUBS 查詢語法 → guid → full document。

**B. GPSS claim1 旗標(BR① D)**
- B1: `gpss_search` / `gpss_to_records` 偵測 US 案 claim1 為空(或僅 "What is claimed is:" 樣板無內文)→ 回 `claim1_empty: true` 旗標,讓 AI 知道該 fallback 到 `patent_get_claim1`/PPUBS。

**C. skill 文件(BR②)**
- C1: patentworks SKILL.md §5 加「來源梯窮舉門檻(Exhaustion Gate)」硬規則:宣告任一欄位(claim1/代表圖/全文/書目)缺失前,必須逐級走完來源梯並在報告留每級實測結果。
- C2: §5 全面更新工具清單:補載 `fetch_patent_pdf` / `extract_representative_figure` / `patentmcp_batch_download_figures` / `ppubs_batch_get_claims`;刪除過時的「PDF 二進位下載端點系統性故障」論斷(line 55),改為「`fetch_patent_pdf` 官方路由優先,失敗才降級」。
- C3: 重寫 §5 爬蟲天條天平:保留「使用前需明確同意 + 單線限速」,新增「同意後 `patentmcp_batch_download_figures` 等單線批量軟性機制是正規合規路徑,`provenance.scraping:true` 是正常標記非違規證據」。

**D. 偵查後決策(需先查 TIPO GPSS API 規格)**
- D1: `gpss_search` 加 `uspc` 參數可行性——若 GPSS 後端支援 US 分類欄位則加參數,否則於 skill 記載「USPC 軸走 `uspto_patents`(PPUBS CCL)」標準樣板。
- D2: INPADOC family——GPSS 不回 family ID;評估啟發式分群(同申請人+同優先權)或於 skill 記載「GPSS 去重=公開號級非家族級」已知限制。

### OUT

- **BR① A:patentmcp 工具未 surface 進 opencode session** — 不在 patentmcp repo,屬 opencode `enablement.json` / MCP App 註冊側。本 spec 只記錄,轉去 opencode 處理。

## Non-Goals

- 不重寫 GPSS headless 爬蟲機制本身(已是單線限速合規)。
- 不改 BigQuery 預算門檻策略。

## Constraints

- 反幻覺:D1/D2 涉及 TIPO GPSS 後端能力,**未經規格確認不得臆造欄位代碼**。
- 不新增 fallback mechanism(天條 §11):A1 是「移除靜默 fallback、改為顯式 gate」,方向正確;其餘不得偷加 fallback。
- 參數 alias 不可破壞既有工具呼叫(向後相容)。

## What Changes

- `src/patent_mcp_server/patents.py`:`fetch_patent_pdf` / `extract_representative_figure` / ppubs dispatcher / 參數命名。
- `src/patent_mcp_server/gpss/client.py` + `screening_table.py`:claim1_empty 旗標。
- `skills/patentworks/SKILL.md` §5:Exhaustion Gate + 工具清單 + 爬蟲天條。
- `issues/`:三份 BR 標記處理進度;A surface 問題轉記。

## Impact

- 任何呼叫 `fetch_patent_pdf` 的流程:預設行為改變(不再靜默爬蟲)——需驗證既有呼叫端。
- 讀 patentworks skill 的所有 priorsearch session:來源梯行為與工具認知更新。
