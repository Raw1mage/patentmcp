# Proposal: patentmcp_gpss4-folder-tools

## Why

TIPO GPSS4 網頁 App (`https://tiponet.tipo.gov.tw/gpss4/`) 登入後有「專案資料夾」會員功能
(patent list 收藏管理)。現有 `src/patent_mcp_server/gpss/client.py` 只走 REST 檢索 API
(單一 `userCode`),**無法**觸及此功能——專案資料夾是 **session-based 會員登入**後的頁面功能,
走自訂 `TTS*` cookie,不是 REST API userCode。

## Original Requirement Wording (Baseline)

- "設計一個 patentmcp 的內部工具,用我的帳號登入系統,操作『專案資料夾』"
- 補充:"登入後有『專案資料夾』功能,會有 patent list CRUD 功能"

## Requirement Revision History

- 2026-07-11: initial draft created via plan-init.ts
- 2026-07-11: 範圍鎖定第一版純讀取(list + export);登入走自動 OCR;形態為 MCP tool。
- 2026-07-11 (SCOPE PIVOT): 專案資料夾路 CLOSED(export 缺 family → dedup 不可信)。改以**登入態「進階檢索」scraping** 為主線:突破 GPSS API 每日下載配額,抓帶 family 的結果列表 → CSV。推翻原 Non-Goal「不做瀏覽器自動化」——family 只能經 playwright 真實瀏覽器取得(URL 帶短命 slot key,httpx 手拼必敗)。

## Effective Requirement Description (SCOPE PIVOT 2026-07-11)

在 patent_mcp_server 建一組 GPSS4 **進階檢索 scraping** 能力,繞過 GPSS API 每日下載配額:
1. 用 `.env` 帳密自動登入 GPSS4(OCR 過 5-GIF CAPTCHA),取得並維護 `TTS*` session cookie jar。
2. 用 playwright 真實瀏覽器(注入 login cookie jar)驅動進階檢索:goto 進階檢索 tab(帶 slot key)→ 填檢索式 `_3_10_X` → image submit → 非同步 job 輪詢(`ttsserv_watch ... <!--DB_OK-->`)→ 結果簡目頁。
3. 抓結果列表:序號/圖式/申請日/專利名稱/摘要 + **家族編號(點『家族收合』後逐筆 famgp 群組,group 參數=dedup 鍵)** → 分頁逐頁 → CSV 落地。
4. session 快過期(90 分)或失效自動重登。

**成敗關鍵已驗證**:結果列表含 family(專利家族數量並列總筆數;每筆 `clickselect(...,group)` 的 group=家族分組鍵)——這正是專案資料夾 export 缺席、導致該路作廢的欄位。

## Scope

### IN

- 登入模組(已完成):`.env` 帳密 → OCR CAPTCHA(5 張單字 GIF)→ POST accserver → 取 TTS* cookie jar → SSO 會員標記判定成功。session 快過期/失效自動重登(既定行為,經使用者批准)。
- **進階檢索 scraper(主線)**:
  - query 送出契約:進階檢索 tab slot-key URL → `_3_10_X` 檢索式(語法 `(詞)@TI` / `CS=xxx` / `AD=y1:y2`)→ image submit。
  - 非同步 job:輪詢 `ttsserv_watch?kmwork/km.swp:<num>:<slot>:全部:` 至 `<!--DB_OK-->` → 結果簡目頁。
  - family 抽取:點『家族收合』→ `tr[name=famgpN]` 逐筆家族群組 + `clickselect(...,group)` group 鍵。
  - 分頁逐頁抓取 + CSV 落地(欄位:專利號/名稱/申請日/摘要/family-group)。

### OUT

- 專案資料夾 CRUD / export(**CLOSED** — export 缺 family,dedup 不可信;端點已逆向但棄用)。
- 標記清單寫入操作(已逆向,非主線)。
- claims 全文入 CSV(簡目頁無 claims,需進詳目每筆多一請求;第一版只帶摘要)。

## Non-Goals

- 不改現有 GPSS REST 檢索 client。
- ~~不做瀏覽器自動化~~(已推翻:family 取得必須 playwright 瀏覽器;純 httpx 因 URL 短命 slot key 無法輪詢到結果頁)。

## Constraints

- 反幻覺:資料夾實際端點鎖在登入牆後,已逆向登入契約,資料夾端點需登入後實測拓出,不得臆造。
- 不新增 fallback(天條 §11):自動重登是既定登入行為經批准;不得偷加其他 fallback。
- 憑證安全:帳密只存活於 `.env` / 進程 env,不寫進 scratch / log。

## What Changes

- `src/patent_mcp_server/gpss4/`(新模組):`session.py`(登入+OCR+cookie 管理)、`folder.py`(讀取)。
- MCP tool 註冊:`gpss4_folder_list/patents/export`。
- `.env.example`:已補 `GPSS4_USERNAME` / `GPSS4_PASSWORD`。
- 相依:OCR engine(數字辨識)。

## Capabilities

### New Capabilities

- `gpss4_folder_list`: 列出登入使用者的專案資料夾。
- `gpss4_folder_patents`: 列出指定資料夾內 patent 清單。
- `gpss4_folder_export`: 匯出資料夾內容。
- gpss4 session:自動登入 + OCR CAPTCHA + session 維護。

### Modified Capabilities

- (none — 純新增,不動既有檢索工具)

## Impact

- 新增外部相依(OCR engine)。
- 新 MCP tool 進工具列;不影響既有檢索工具。
