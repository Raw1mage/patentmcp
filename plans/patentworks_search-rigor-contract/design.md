# Design: patentworks_search-rigor-contract

## Context

priorsearch flow 的檢索強度從來只靠散文約束，無任何機檢閘。本設計把「檢索夠不夠廣」變成**可解析、可計分、可 PASS/FAIL** 的契約，並統一兩套矛盾的資料樹。核心分工原則不變：**AI 留檢索證據（matrix-log）→ 工具稽核證據（search_audit）**，工具不代跑檢索（不重造查詢/爬蟲輪子）。

## Goals / Non-Goals

### Goals
- 讓「隨便檢幾條交差」在交付前被一道 machine-checkable 閘擋下。
- 把 USPC 提升為與 IPC/CPC 並列的一級限縮軸。
- 單一資料樹真相，消除平行管線。

### Non-Goals
- 不做自動檢索、不在 server 端發查詢。
- 不改報告章節結構、不動 PDF/圖降級與 token 紀律。

## Decisions

- **DD-1｜檢索證據的單一真相是 `matrix-log.jsonl`（取代自由格式 matrix-log.md）**
  現行 `01_search/matrix-log.md` 是人寫的自由表格，無法機檢。改為**結構化 JSONL**（一行一查詢），`search_audit` 解析它做覆蓋率計分。報告 §1 的人類可讀表格由 JSONL 渲染而來（衍生，不再是真相源）。
  每行 schema：
  ```json
  {
    "query_id": "Q07",
    "source": "gpss",                    // gpss|epo|uspto|google
    "database": "USA",                   // TWA/TWB/CNA/CNB/USA/USB or epo/google region
    "axis": {
      "class_codes": ["G06Q50/08"],      // IPC/CPC/USPC 之一或多
      "class_scheme": "ipc",             // ipc|cpc|uspc
      "keywords": ["escrow"],            // 該查詢用的關鍵字（單一複合詞或片語）
      "concept_group": "A",              // 對應 campaign 概念群 A-E
      "boolean": "AND",                  // AND|OR|SINGLE — 此查詢的組合運算子
      "date_from": "2015-01-01",
      "date_to": "2026-06-28"
    },
    "hits": 42,                          // 回傳命中數
    "raw_ref": "raw/Q07.json"            // 落地原始 JSON 的相對路徑
  }
  ```
  *taxonomy*：`query_id`=查詢序號（復現錨）；`axis`=這條查詢在「分類×關鍵字×概念群×布林×日期」五維中的座標；`hits`=命中數（0 也要記，零命中是有效證據）；不允許把 `axis` 解讀成「願望」——它是實際送出的參數快照。

- **DD-2｜檢索強度的可數最低門檻（campaign 可覆寫，但有硬地板）**
  `00_campaign.md` 宣告本案 target，`search_audit` 用以下**預設硬地板**機檢（campaign 可往上調，不可往下破）：
  | 維度 | 符號 | 預設地板 | 說明 |
  |---|---|---|---|
  | 分類錨點數 | `min_class_anchors` | ≥ 3 | 不同分類碼（跨 IPC/CPC/USPC）至少 3 個 |
  | 關鍵字概念群數 | `min_concept_groups` | ≥ 3 | campaign 定義的 A-E 概念群至少觸及 3 群 |
  | 三地覆蓋 | `min_jurisdictions` | = 3 | TW+CN+US 皆需有查詢（除非 campaign 明示排除某地並記理由） |
  | AND/OR 組合 | `min_boolean_combos` | ≥ 2 | 至少出現 2 種布林型態（不可全 SINGLE 單詞海撈） |
  | USPC 入軸 | `uspc_required` | true（US 案） | US 檢索至少 1 條以 USPC 為 class_scheme |
  | 總查詢筆數 | `min_queries` | ≥ 12 | 五維交叉的最低笛卡兒覆蓋（3 錨點 × ~4 概念/地，去重後地板） |
  *taxonomy*：「地板」=不可破的最低標；campaign 覆寫只能調高。`uspc_required` 對非美檢索不適用（TW/CN 無 USPC）。

- **DD-3｜`search_audit` 是純稽核工具，PASS/WARN/FAIL 三態**
  比照 `screening_table.py` 的 server-side 落地範本，新增 `src/patent_mcp_server/search_audit.py`（純函式）+ `patents.py` 一個 `@mcp.tool()` 薄包裝。
  - 輸入：`matrix_log_path`（JSONL）、`campaign_path`（可選，讀覆寫門檻）。
  - 輸出 envelope：
    ```json
    {
      "verdict": "PASS|WARN|FAIL",
      "coverage": {"class_anchors": 4, "concept_groups": 3, "jurisdictions": 3,
                   "boolean_combos": 2, "uspc_in_axis": true, "queries": 14},
      "thresholds": { ...生效門檻（地板或 campaign 覆寫後）... },
      "gaps": ["..."],          // FAIL/WARN 時，逐條指出缺哪一軸（e.g. "USPC 未入軸"）
      "per_jurisdiction": {"TWA": 5, "CNA": 4, "USA": 5}  // 各庫查詢分佈
    }
    ```
  - 判定：任一維度低於地板 → `FAIL`；全達標但分佈嚴重偏斜（某地 < 2 條）→ `WARN`；全綠 → `PASS`。
  - **不發任何網路請求**；純讀檔計分。FAIL 訊息要可操作（指出補哪一軸）。
  *taxonomy*：`verdict`=機檢結論，FAIL 即不得交付；`gaps`=補救指令清單，非建議；`coverage`=實測值；不允許把 WARN 當 PASS 交差。

- **DD-4｜priorsearch.md 複核閘語意反轉：先驗過程、再驗產物**
  §3.B step 4 主代理複核從「查 candidates.csv 整不整齊」改為兩段：
  1. **先**對 `matrix-log.jsonl` 跑 `search_audit` → 必須 PASS（FAIL 則回 §3.B step 3 補查，不得前進）。
  2. **再**做原本的 CSV 品質複核（件數/欄位/分佈）。
  §3.D step 8 交付前再跑一次 `search_audit` 作為最終強制閘（與 docx probe `ok=True` 並列）。

- **DD-5｜統一資料樹：以 priorsearch.md §0 的 `priorart_<topic>/` 為唯一真相，廢止 SKILL.md 的平行 Data Tree**
  兩套衝突中，`priorart_<topic>/`（00_campaign…99_deliverables 分層）較完整且已對齊 docxmcp package，留它。SKILL.md §Data Tree 整段改為**指標**：「資料樹規範見 `flows/priorsearch.md §0`」，並保留 candidates.csv 欄位格式與 5 張圖命名（這兩項 priorsearch.md 未細列，移植過去）。新增 `01_search/matrix-log.jsonl` 取代 `.md`。
  *taxonomy*：「唯一真相」=只有一處定義目錄結構，其他檔案只引用不複述。

- **DD-6｜fig2 命名修正連帶處理**
  SKILL.md §4 圖表命名 `fig2_scenario.png` 註解已是「相關性分佈（取代原情境分佈）」，但檔名仍 scenario，造成語意漂移。統一後在資料樹規範註明 `fig2` 用途為相關性分佈，檔名維持 `fig2_relevance.png`（新案用），舊 `fig2_scenario.png` 標為 legacy alias。

## Risks / Trade-offs

- **R1**：硬地板數值（≥3/≥3/≥12…）可能對極窄領域過嚴 → 緩解：campaign 可上調但設「明示排除 + 記理由」逃生門（記在 campaign，audit 讀得到），不是 silent skip。
- **R2**：matrix-log.jsonl 增加子代理落地負擔 → 緩解：schema 精簡，子代理本就要寫 matrix-log，改格式不加實質工作。
- **R3**：search_audit 與既有 27 工具命名/註冊衝突 → 緩解：比照 screening_table 模式，已驗證可行。

## Critical Files

- `src/patent_mcp_server/search_audit.py`（新）— 純函式 schema parser + 覆蓋率計分。
- `src/patent_mcp_server/patents.py`（改）— 加一個 `@mcp.tool() search_audit(...)`（約 line 2512 區塊後）。
- `skills/patentworks/flows/priorsearch.md`（改）— §0 matrix-log.jsonl、§2 USPC 升軸、§3 複核閘反轉、新增 search_audit 強制閘、§DD-2 門檻表。
- `skills/patentworks/SKILL.md`（改）— §Data Tree 改指標 + 移植 candidates 欄位/圖命名。
- `.capability-installed.json` republish 觸發（XDG projection）。

## Validation Plan

1. `search_audit.py` 單元測試：餵 3 組 matrix-log.jsonl（充分/缺 USPC/筆數不足），斷言 verdict 與 gaps 正確。
2. patentmcp server 重啟後 `GET /tools` 確認 `search_audit` 註冊成功、schema 正確。
3. 用 TWCID 既有 search_results.csv 的反推 matrix-log 餵 audit，確認「薄檢索」會被 FAIL（回歸驗證：證明這道閘真能擋下這次的問題）。
4. priorsearch.md 改寫後人讀復查：複核閘語意是否真的先過程後產物。
5. republish 後 XDG projection diff 確認同步。
