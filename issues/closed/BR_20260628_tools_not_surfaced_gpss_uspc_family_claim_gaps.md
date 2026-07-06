# BUG REPORT: 工具未 surface 進 session、GPSS 缺 USPC/家族軸、US 案 Claim1 回空

**Date**: 2026-06-28
**Status**: Resolved (2026-07-06 收敲) — A Resolved(dual UDS+TCP，工具已 surface)；B VOID(USPC 退場)；C Resolved(誠實揭露路線)；D Resolved(`_gpss_search_impl` 已帶 `claim1_empty` 旗標 + `claim1_audit{empty_count, empty_pubnos[]}`，patents.py:2585-2601；skill §5 已載 PPUBS fallback 觸發訊號)
**Priority**: High
**Reporter**: AI Agent (代表 User)
**Source Session**: iSafe2.0 專利報告 R2 改良（GPSS-only 重檢索）

---

## 1. 磨擦點與問題描述 (Friction Points)

### A. patentmcp 工具未 surface 進 opencode session 工具目錄（最大阻塞）

> **Status: RESOLVED (2026-06-28)** — 真因不是「opencode 註冊路徑不一致」,而是 **patentmcp 自身 compose drift**:commit `3044b1f`「expose port 8000 for direct IDE connection」把 inward UDS 換成 TCP-only,但 `mcp.json` 仍宣告 `unix://...sock:/mcp/` → opencode 依標準 fail-fast skip 連不到的 socket(行為正確)→ 工具不注入。依 `specs/mcp-integration-standard`(opencode repo)R1.2 + 使用者裁定,改為 **dual UDS+TCP**:`serve()` 改單一 uvicorn.Server 多 socket 綁定(FastMCP lifespan 只能跑一次,不可用 bodesign 兩 Server+gather)、compose command 還原 `--uds ... --port 8000`、healthcheck 改 `test -S socket`。`webctl.sh restart` 重建後 socket 出現(0666)、UDS+TCP /health 皆 ok、session 工具目錄出現 22 個 `patentmcp_*`(重建前 0 個)。對應 opencode issue `issue_20260628_patentmcp_tools_not_surfaced_in_session`(已移 observing)。

- **現象**：R2 要實際跑線上重檢索（`gpss_search` 等），但發現：
  - opencode session 的 `enablement.json` configured mcp 只有 `drawmiat / docxmcp / bodesign / specbase`，**沒有 patentmcp**。
  - 214 個 on-demand 工具裡也沒有 `gpss_search`。
  - `system-manager_toggle_mcp(patentmcp)` 回報 config 找不到（它是 MCP App，不是 opencode.json 的 MCP）。
  - 但容器本身健康跑在 `:8000`（`/health ok`，28 工具含 search_audit + gpss_search 都在）。
- **後果**：被迫用 `curl` 走容器的 `/mcp` Streamable HTTP 端點，手動做 JSON-RPC handshake（initialize → initialized → tools/call）來驅動 `gpss_search`，並自寫 `mcp_call.sh` harness。**這違反「優先用原生工具、禁徒手造輪子」的精神**——但工具沒 surface，沒有原生路徑可走。
- **RCA**：patentmcp 以 MCP App 形式安裝（容器化 + UDS/TCP），但它的工具沒有被注入進 opencode session 的工具目錄。`docxmcp / specbase` 等是直接 surface 的（我能直接呼叫 `docxmcp_document`），patentmcp 卻不是。兩者註冊路徑不一致。
- **建議修復**：
  1. 確認 patentmcp 是否該像 docxmcp 一樣把 `patentmcp_*` 工具 surface 進 session。若是，修正註冊/enablement 讓 `gpss_search / search_audit / epo_* / uspto_* / build_screening_table` 等可直接呼叫。
  2. 若設計上就是「容器服務、不 surface」，則應在 companion skill / instructions 明確記載官方驅動路徑（`/mcp` JSON-RPC 或某個 bridge 工具），不要讓 AI 每次自己摸索 curl handshake。

---

#### ✅ RCA 回覆（opencode 側，2026-06-28）— §A **非 opencode 缺陷，真因在 patentmcp 自己的 compose**

> 由 opencode 維護者偵查回覆。原 issue 副本見 opencode repo `issues/issue_20260628_patentmcp_tools_not_surfaced_in_session.md`（含完整 source 引用）。
>
> **結論：opencode 端不需改任何 code。** §A 的 root cause 在 patentmcp 自己的 `docker-compose.yml`，屬本 repo 可自行修復。

**RCA 推翻原假設**（「兩者註冊路徑不一致」）。實測 opencode 的 App 注入路徑**完全一致且正確**：`~/.config/opencode/mcp-apps.json` 裡 6 個 app（docxmcp / bodesign / patentmcp / formmcp / gmail / google-calendar）全走同一條 `connectMcpApps()` + `McpPrerequisite.probe()`。其中 docxmcp / bodesign（與 patentmcp **同形**的 UDS streamable-http app）都正常 surface 進 session（`docxmcp_*` / `bodesign_*` 可直接呼叫），patentmcp / formmcp 缺席。

**真因（硬證據）**：

- patentmcp 的 `mcp.json` / opencode `mcp-apps.json` 宣告連線端點是 **UDS**：`transport=streamable-http, url=unix:///home/pkcs12/projects/patentmcp/.run/patentmcp.sock:/mcp/`。
- 但 `docker-compose.yml:25` 的 command 是 `["--transport","http","--host","0.0.0.0","--port","8000"]` — **TCP-only，從不 bind 那個 UDS socket**。
- 證據：host `.run/` 無 socket 檔；`docker exec patentmcp` 看 `/run/patentmcp/` 空、`/proc/net/unix` 無 patent socket；`/health` 只在 TCP `:8000` 回應。
- opencode 的 prerequisite gate（`packages/opencode/src/mcp/prerequisite.ts:120-136`）對 `unix://` url 會檢查 `pathExists(socketPath)` → 不存在 → `missing.kind=reachable` → **fail-fast skip + recordAppFailure**（by design，無 silent fallback）→ 工具不注入。
- 對照組 docxmcp 的 compose command 是 `["--transport","http","--uds","/run/docxmcp/docxmcp.sock"]` → bind UDS → socket 存在 → surface 正常。
- **patentmcp server 本身已支援 `--uds`**（`src/patent_mcp_server/patents.py:2918`、`_http_app.serve(uds=...)`:326），只是 compose 沒傳。BR 作者看到容器 TCP `:8000` healthy 就以為該 surface，但 opencode 從不連 `:8000`，只連宣告的 UDS。

**本 repo 的修復（擇一，建議 1）**：

1. **（建議）改 `docker-compose.yml` command 走 UDS**，對齊 docxmcp：
   ```yaml
   command: ["--transport", "http", "--uds", "/run/patentmcp/patentmcp.sock"]
   ```
   `./.run:/run/patentmcp` 的 bind mount 已存在；`ports: 8000:8000` 可保留（給人類 landing page / 跨機 TCP），也可拿掉。重建容器後 socket 出現，opencode 下次 tool-resolve 會**自動** surface `patentmcp_*`（prereq 有 retry/backoff）。
2. 若要維持 TCP-only：把 `mcp.json` 與 opencode `mcp-apps.json` 的 url 改成 `http://127.0.0.1:8000/mcp/`。但 UDS 是本 fleet 慣例（docxmcp/bodesign/formmcp 皆 UDS），建議走 (1)。

**驗證**：修復後 `ls .run/patentmcp.sock` 應存在 → AI 在 opencode session 內可直接呼叫 `gpss_search(...)`，無需 curl handshake。

> 附帶觀察：`formmcp` 也因同類原因（launcher 行程死掉、socket 無人 listen）未 surface，但那是它自己的運維問題，與本 BR 無關。

---

### B. `gpss_search` 缺 `uspc` 參數 — USPC 軸無法在 GPSS 直接限縮

> **Status: VOID（作廢，非缺陷，2026-06-28）** — USPC 已全面退場(使用者規則 2026-06-28,commit `b7c5b0a` 移除 search_audit 的 `uspc_required` floor;後續 commit `da207d1` 清乾淨殘留 docstring / dead-field)。USPC 既不採用,`gpss_search` 沒有 `uspc` 參數即為**正確狀態**,本項不再是待修缺陷。分類軸僅用 CPC/IPC,兩者都能在 GPSS 一站 AND。

- ~~**現象**：本 session 才剛把 USPC 升為 search_audit 的一級限縮軸...~~（前提已不成立:USPC 退場）
- **處置**：作廢。CPC/IPC 為唯一分類軸,GPSS 原生支援,無缺口。

### C. `gpss_search` 不提供 INPADOC 家族 ID — 無法做家族 collapse

> **Status: Resolved（誠實記載路線，2026-06-28，commit 待補）** — 採「誠實揭露限制」而非啟發式分群。**不做**「同申請人+同優先權」的啟發式家族（天條 #11 禁 fabrication:啟發式會製造假家族、誤導去重）。真家族級 collapse 一律走官方 `epo_family`。
>
> **修復內容**：
> 1. `screening_table.py` `KNOWN_GAPS["family"]` 訊息修正——原寫「**Google 路**無 family_id」誤導(暗示 GPSS 有),改為「**GPSS 與 Google 路皆不提供** INPADOC family_id;去重僅到公開號級,家族級 collapse 須走 `epo_family`」。
> 2. `patents.py` `build_screening_table` 的 gaps filter 原條件 `source=="google" or k in (legal_status,citations)`,GPSS 來源時 family 不 surface(沉默缺口);改為 family **不論來源都揭露**。
> - **live 驗證 PASS**:`build_screening_table(cpc=G06Q50/08, databases=[USA])` 回 `source:gpss`、`gaps:{family:"GPSS 與 Google 路皆不提供 INPADOC family_id..."}`。skill §5 已記載此限制。

- **現象**：455 筆候選只能以「公開號」去重，無法做全球專利家族（INPADOC family）collapse。報告 §六 誠實標註了此限制。
- **RCA**：GPSS 搜尋介面不回傳 family ID。EPO OPS（`epo_family`）才有，但需另外逐件查、且有每週 4GB 流量限制，對 455 筆批量不切實際。
- **建議修復**：評估在 `gpss_search` 結果補一個輕量 family 線索欄位（即使只是同申請人+同優先權的啟發式分群），或在 companion skill 記載「GPSS 去重 = 公開號級，非家族級」的已知限制，避免每次重新踩。

### D. 美國案 `gpss_search` 回傳 Claim 1 為空

- **現象**：`US20230081319A1`（5 分核心前案）經 GPSS 回傳的請求項內容為空字串（`claim1: "What is claimed is:"` 後無內文），導致報告該案只能以摘要解析，無逐字 Claim 1。
- **RCA**：GPSS 對部分美國公開案的 claim 全文擷取不完整。依 patentworks skill §5 來源優先序，US 逐字 claims 本應走 `uspto_patents`（PPUBS）或 `google_get_patent_claims`（BigQuery），但後者已禁用、前者未在本次補抓。
- **建議修復**：在 `gpss_search` 偵測到 claim 內容為空時，回傳一個明確旗標（如 `claim1_empty: true`），讓 AI 知道該自動 fallback 到 `uspto_patents` 補抓，而非靜默交出空 claim。

---

## 2. 影響範圍 (Blast Radius)

- A 影響**所有**想在 opencode session 內跑專利檢索的任務——沒 surface 就只能 curl 繞道。
- B/C/D 影響每一份 priorsearch 報告的檢索完整度與 search_audit 達標路徑。

## 3. 驗證手段 (Validation Plan)

- A：修復後，AI 應能在 session 內直接呼叫 `gpss_search(...)`，無需 curl handshake。
- B：USPC 限縮應有單一可執行路徑（GPSS `uspc` 參數，或 skill 記載的 `uspto_patents` 樣板）。
- D：對 claim 為空的美國案，工具應回旗標觸發 fallback，最終報告不再出現空 Claim 1。
