# Proposal: patentmcp_gpss-web-boolean-search

## Why

- **前提推翻**：先前「US 因 GPSS 布林弱才走 EPO」的路由決策，前提是「GPSS 英文括號布林表達力弱」。官方文件 (TIPO help.html 九、檢索語法說明) + 沙盤推演證實此前提**不成立**——GPSS 原生支援欄位化括號布林式。
- **成本動機**：GPSS API 端點 (`gpss_api` REST) 受 condition-length 額度硬閘與每時段配額限制；而**人類登入路徑 (gpss3 網頁) 做「檢索計數 / 取結果」不燒 API quota**。用網頁路徑檢索可省大量額度成本。
- **能力缺口**：現有 `patents.py` 的 gpss3 爬蟲基礎設施只實作到「單號 → 詳目 → 抓圖」，**沒有布林檢索計數 / 結果取得入口**。

## Original Requirement Wording (Baseline)

- "我們目前的決策是 US 用 EPO 查，TW/CN 用 GPSS 掃"
- "英文 keyword 的括號語法只有 EPO 才有辦法正確表達。其實 GPSS 應該也行，只是 mcp tool 可能不知道正確的打法。我記得 GPSS 是可以這樣組合關鍵字的：(health monitoring AND heartbeat)@CL"
- "你只要能產生單一檢索式就能解決"
- "把人類路徑布林檢索工具建起來。超過30萬上限沒有救的必要，我們只關心有意義的檢索結果。所以你要懂得限縮條件，包含日期、國別"

## Requirement Revision History

- 2026-07-16: initial draft created via plan-init.ts
- 2026-07-16: 需求確立——建 gpss3 人類登入路徑布林檢索工具；設計原則：單一檢索式承載欄位/日期/國別限縮；大母數 (>30萬) 不救、須主動限縮。

## Effective Requirement Description

1. 新增一個 MCP 工具 (暫名 `gpss_web_search`)，走 **gpss3 人類登入路徑** (網頁爬蟲，非 `gpss_api` REST)，接受**單一欄位化括號布林檢索式**字串，回傳精確命中筆數 (各資料庫分項) 與結果列書目。
2. 工具必須**內建限縮條件支援**：日期範圍 (`ID=YYYYMMDD:YYYYMMDD`)、國別 / 資料庫 (`patDB` 選 TWA/USA/CNA/…)。
3. 檢索式語法遵循 GPSS 官方人類路徑語法：`(A or B)@TI`、`(A)@TI,CL` 跨欄位、`(A)@TI not (B)@AB` 跨欄位布林、鄰近運算 `(電路[1,7]感測器)@TI`。
4. 大母數保護：命中 >30萬 (GPSS 模糊上限) 時 fail-fast 提示使用者**必須限縮** (加日期 / 國別 / 收窄布林)，不回無意義的巨量結果，不嘗試「救」出精確數。

## Scope

### IN
- gpss3 人類登入 handshake 複用 (`_gpss_client` + `_GPSS_POLICY` + INFO token + action URL)
- 單一檢索式 POST 進 `_21_1_T` 欄位
- AJAX 筆數輪詢 (`ttsserv_watch` 端點) 取各資料庫精確命中數
- 日期 / 國別 / 資料庫限縮 (編進檢索式字串 + `patDB` 參數)
- 結果列書目解析 (複用既有 `_gpss_iter_result_rows` / `_gpss_select_detail_link` 模式)
- 大母數 >30萬 fail-fast + 限縮提示
- 檢索式語法驗證 (欄位代碼白名單、`@欄位` 後綴合法性)

### OUT
- **不下載** PDF / 圖式 (那是既有 `gpss_download_*` 工具的職責；本工具純檢索計數 + 書目)
- 不改 `gpss_api` REST 路徑 (`patent_search` 來源梯不動)
- 不改 US→EPO 路由決策 (那是後續獨立決策，本工具只是提供「GPSS 布林夠強」的能力證據)
- 不做網頁登入態的加值功能 (統計分析 / 圖表分析 / 專案資料夾，那些需登入帳號)

## Non-Goals

- 不追求「救」出 >30萬 的精確母數——大母數本身就不是有意義的檢索結果。
- 不重構 gpss3 表單分欄邏輯——欄位限定靠檢索式字串內的 `@欄位` 語法，非表單分欄。

## Constraints

- **Cloudflare 節流天條**：所有 gpss3 請求必須序列化走 `_GPSS_POLICY` (Concurrency=1 + random pacing + cooldown)，不得並行觸發 Managed Challenge。
- **不新增 fallback** (使用者天條)：檢索式非法 / 大母數 / handshake 失敗一律 fail-fast + 顯式報錯，不靜默降級。
- **XDG scratch 天條**：探偵 / 中間 HTML 落 `$XDG_RUNTIME_DIR`，不落 /tmp、不落工作區網路掛載。
- **零 API 額度**：本工具走網頁路徑，不得誤呼叫 `gpss_api` REST 燒 quota。

## What Changes

- `src/patent_mcp_server/patents.py`：新增 `gpss_web_search` 工具 + 內部實作 (複用 handshake / policy / 結果列解析)。
- `src/patent_mcp_server/gpss/`：可能新增檢索式語法驗證 helper (欄位代碼白名單)。
- MCP 工具註冊：暴露 `gpss_web_search`。
- SKILL.md：來源梯 GPSS 條目補「網頁路徑布林檢索工具」使用紀律 (何時用網頁計數 vs API 實撈)。

## Capabilities

### New Capabilities
- `gpss_web_search(expr, date_from?, date_to?, databases?, ...)`: 走 gpss3 人類路徑，單一欄位化括號布林式檢索，回各資料庫精確命中數 + 結果列書目，零 API 額度。

### Modified Capabilities
- 來源梯 GPSS 判讀紀律 (SKILL)：新增「檢索計數優先走網頁路徑省額度」的操作分流。

## Impact

- **affected code**: `patents.py` (新增工具)、`gpss/` (語法驗證)、MCP 工具註冊、SKILL.md、architecture.md
- **operators**: 檢索計數 / landscape 探量時多一條省額度路徑
- **決策鏈**: 提供「GPSS 布林足夠」的能力證據，US→EPO 路由可據此重評 (但屬後續獨立決策)
