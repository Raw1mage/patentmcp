# BUG REPORT: 工具未 surface 進 session、GPSS 缺 USPC/家族軸、US 案 Claim1 回空

**Date**: 2026-06-28
**Status**: Open
**Priority**: High
**Reporter**: AI Agent (代表 User)
**Source Session**: iSafe2.0 專利報告 R2 改良（GPSS-only 重檢索）

---

## 1. 磨擦點與問題描述 (Friction Points)

### A. patentmcp 工具未 surface 進 opencode session 工具目錄（最大阻塞）

* **現象**：R2 要實際跑線上重檢索（`gpss_search` 等），但發現：
  * opencode session 的 `enablement.json` configured mcp 只有 `drawmiat / docxmcp / bodesign / specbase`，**沒有 patentmcp**。
  * 214 個 on-demand 工具裡也沒有 `gpss_search`。
  * `system-manager_toggle_mcp(patentmcp)` 回報 config 找不到（它是 MCP App，不是 opencode.json 的 MCP）。
  * 但容器本身健康跑在 `:8000`（`/health ok`，28 工具含 search_audit + gpss_search 都在）。
* **後果**：被迫用 `curl` 走容器的 `/mcp` Streamable HTTP 端點，手動做 JSON-RPC handshake（initialize → initialized → tools/call）來驅動 `gpss_search`，並自寫 `mcp_call.sh` harness。**這違反「優先用原生工具、禁徒手造輪子」的精神**——但工具沒 surface，沒有原生路徑可走。
* **RCA**：patentmcp 以 MCP App 形式安裝（容器化 + UDS/TCP），但它的工具沒有被注入進 opencode session 的工具目錄。`docxmcp / specbase` 等是直接 surface 的（我能直接呼叫 `docxmcp_document`），patentmcp 卻不是。兩者註冊路徑不一致。
* **建議修復**：
  1. 確認 patentmcp 是否該像 docxmcp 一樣把 `patentmcp_*` 工具 surface 進 session。若是，修正註冊/enablement 讓 `gpss_search / search_audit / epo_* / uspto_* / build_screening_table` 等可直接呼叫。
  2. 若設計上就是「容器服務、不 surface」，則應在 companion skill / instructions 明確記載官方驅動路徑（`/mcp` JSON-RPC 或某個 bridge 工具），不要讓 AI 每次自己摸索 curl handshake。

### B. `gpss_search` 缺 `uspc` 參數 — USPC 軸無法在 GPSS 直接限縮

* **現象**：本 session 才剛把 USPC 升為 search_audit 的一級限縮軸，但實際檢索時發現 `gpss_search` 的參數只有 `cpc` / `ipc`，**沒有 `uspc`**。在 BigQuery 已被禁用（預算超支）的前提下，USPC 軸只能改走 `uspto_patents`（PPUBS `CCL/705/300`），無法在主檢索引擎一站完成。
* **後果**：USPC 軸與其他軸不對稱——CPC/IPC 能在 GPSS 一次 AND 進去，USPC 要跳到另一個工具、另一套查詢語法。最後在 search_audit 把 USPC 從強制降為非強制（已 commit），但這是被工具限制逼出來的妥協，不是設計初衷。
* **RCA**：GPSS 後端（TIPO）本身的檢索式可能支援美國分類，但 `gpss_search` 的參數介面沒暴露 `uspc`。
* **建議修復**：若 GPSS 後端支援，於 `gpss_search` 增 `uspc` 參數；否則在 companion skill 明確記載「USPC 軸必走 `uspto_patents`」並提供標準查詢樣板，讓 search_audit 的 USPC 要求有對應的可執行路徑。

### C. `gpss_search` 不提供 INPADOC 家族 ID — 無法做家族 collapse

* **現象**：455 筆候選只能以「公開號」去重，無法做全球專利家族（INPADOC family）collapse。報告 §六 誠實標註了此限制。
* **RCA**：GPSS 搜尋介面不回傳 family ID。EPO OPS（`epo_family`）才有，但需另外逐件查、且有每週 4GB 流量限制，對 455 筆批量不切實際。
* **建議修復**：評估在 `gpss_search` 結果補一個輕量 family 線索欄位（即使只是同申請人+同優先權的啟發式分群），或在 companion skill 記載「GPSS 去重 = 公開號級，非家族級」的已知限制，避免每次重新踩。

### D. 美國案 `gpss_search` 回傳 Claim 1 為空

* **現象**：`US20230081319A1`（5 分核心前案）經 GPSS 回傳的請求項內容為空字串（`claim1: "What is claimed is:"` 後無內文），導致報告該案只能以摘要解析，無逐字 Claim 1。
* **RCA**：GPSS 對部分美國公開案的 claim 全文擷取不完整。依 patentworks skill §5 來源優先序，US 逐字 claims 本應走 `uspto_patents`（PPUBS）或 `google_get_patent_claims`（BigQuery），但後者已禁用、前者未在本次補抓。
* **建議修復**：在 `gpss_search` 偵測到 claim 內容為空時，回傳一個明確旗標（如 `claim1_empty: true`），讓 AI 知道該自動 fallback 到 `uspto_patents` 補抓，而非靜默交出空 claim。

---

## 2. 影響範圍 (Blast Radius)

* A 影響**所有**想在 opencode session 內跑專利檢索的任務——沒 surface 就只能 curl 繞道。
* B/C/D 影響每一份 priorsearch 報告的檢索完整度與 search_audit 達標路徑。

## 3. 驗證手段 (Validation Plan)

* A：修復後，AI 應能在 session 內直接呼叫 `gpss_search(...)`，無需 curl handshake。
* B：USPC 限縮應有單一可執行路徑（GPSS `uspc` 參數，或 skill 記載的 `uspto_patents` 樣板）。
* D：對 claim 為空的美國案，工具應回旗標觸發 fallback，最終報告不再出現空 Claim 1。
