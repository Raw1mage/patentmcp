# BR_20260709 — patent_search 純 keyword 檢索 GPSS 級失敗（合併版）

> **狀態：CLOSED（來源梯本身正常、非阻塞）+ 一個 open 待驗證子項（純 keyword GPSS command 形式，卡 TIPO 配額無法端到端驗證）**
> 本檔為 **合併版**——原有兩份同名 BR_20260709（`issues/` open 版 vs `issues/closed/` 舊版）結論互相矛盾，於 2026-07-09 用 MCP rail 端到端實測裁決後合併。舊兩版的定性下方逐段保留並標明何者被推翻。

---

## 一、症狀（原始回報）

`patent_search` / `patent_bulk_export` 對某些查詢官方三源全回 error、最終 `SCRAPING_REQUIRED` fail-fast，無法建全景池。原始 provenance（某時刻）：

| source | status | reason |
|---|---|---|
| gpss | error | `No search command` |
| epo | error | `parse error: 'ops:world-patent-data'` |
| ppubs | error | `unauthorized` / `zero_hits` |
| gpatents | skipped | scraping_not_authorized |

---

## 二、三段診斷史（時間序，含互相推翻關係）

### 診斷 1（舊 closed 版，subagent）— 「stale process，restart 已解」 → **被推翻**

subagent 用 `.venv` python 直跑 `dispatch_search` 得 `total=300000` 成功，判「磁碟 code 正常、長駐 MCP server 進程 stale，restart 解決」。
**推翻證據**：其測試查詢**帶分類軸**故成功；restart 後透過 MCP rail 用錯欄位仍失敗。restart 是巧合，非真根因。

### 診斷 2（舊 closed 版，orchestrator 裁決）— 「呼叫端傳連字號 `TI-AB`，GPSS 不認」 → **部分正確，但非全部**

`keyword_field="TI-AB"`（連字號）→ GPSS 不認該欄位 → `No search command`；改斜線 `TI/AB` → success。
**正確處**：連字號欄位名確實會觸發 `No search command`，呼叫端須用斜線式。
**不完整處**：診斷 2 據此宣稱「無需改 code、BR 關閉」。但 open 版用**正確斜線格式**重測，發現純 keyword（斜線正確、無分類軸）**仍**失敗——存在連字號以外的第二層問題。

### 診斷 3（open 版）— 「純 keyword 無分類軸，GPSS 拒收純全文檢索指令」 → **root cause 方向成立，但修法未驗證**

open 版同時刻對照實測（配額因素被抵消）：
| 呼叫 | 結果 |
|---|---|
| `ipc=G08B21`（純分類軸） | ✅ success |
| `ipc=G08B21 + keyword`（分類軸+keyword，斜線正確） | ✅ success |
| 純 keyword `TI/AB`（斜線正確、無分類軸） | ❌ GPSS `No search command` |

**root cause（code path）**：`search_dispatcher.py::_run_gpss`（line 151-152）對純 keyword，conditions 只組一條 `GPSSCondition("TI/AB", keyword)`。TIPO GPSS API 不接受「只有 TI/AB 全文欄位、無任何分類(IC/CS/UC)或號碼(PN)軸」的 request 作為有效檢索指令 → 回 `No search command`。`_bulk_pull_gpss` 因 DD-4 只用分類軸，不受影響。

---

## 三、Orchestrator MCP rail 端到端裁決（2026-07-09，最新，決定性）

用 `mcpapp-patentmcp_patent_search` 工具（走真實 server 進程單例）實測：

| 查詢 | GPSS provenance | 最終 |
|---|---|---|
| `ipc=G08B21, db=CN, num=3` | error / **Over download quantity** | ✅ success, source=**epo**, total=225833 |
| `keyword=sensor, TI/AB, db=CN, num=3` | error / **Over download quantity** | ✅ success, source=**epo**, total=11368631 |

（`.venv` raw REST 探針同時刻對 pure_kw / ipc_only / kw+ipc 五種組合皆回 `Over download quantity` → 證實配額為當下全域外部狀態，非 command 差異。）

**兩個決定性結論**：

1. **來源梯本身正常、不阻塞**：GPSS 任一 error（`No search command` / `Over download quantity`）都會沿梯退 EPO/PPUBS，最終仍成功命中。原始症狀「三源全 error → SCRAPING_REQUIRED」是**當時 GPSS + EPO(parse error) + PPUBS(unauthorized) 三源恰好同時壞**的疊加，不是純 keyword 單一根因。純 keyword 現在能成功（退 EPO）。

2. **GPSS 當下失敗 = TIPO 配額（`Over download quantity`）**，連純分類軸也一樣被拒。這是暫時性外部狀態，**污染了純 keyword 的鑑別窗口**——當下無法重現 open 版的 `No search command`，也**無法真實驗證任何純 keyword 修法是否被 GPSS 接受**。

---

## 四、結論與去向

### 已定案（CLOSE 本 BR 主體）
- **來源梯正常運作，patent_search 官方路徑實質可用**（GPSS 掛則退 EPO/PPUBS）。原始「三源全掛」是多源同時故障 + 配額疊加的一次性事件，非 code 阻塞。
- 呼叫端**必須用斜線式 `keyword_field`（`TI/AB`），不可用連字號 `TI-AB`**（診斷 2 的有效教訓，已是 skill/工具預設值）。

### Open 待驗證子項（不阻塞，另行追蹤）
- **純 keyword（無分類軸）在 GPSS 級是否有獨立缺陷、以及正確修法**：open 版 root cause 方向（TIPO 拒無分類軸純全文）成立，但：
  - 目前 GPSS 配額被封（`Over download quantity`），**無法端到端驗證任何修法**（規格合約未經真實 GPSS 驗證前不得盲改 `_run_gpss`）。
  - **影響有限**：純 keyword 即使 GPSS miss，仍退 EPO/PPUBS 成功；宏觀窮盡一律走分類軸錨定（`patent_search ipc=` / `patent_bulk_export`），該路徑正常。
- **修法方向（待配額恢復後驗證）**：`_run_gpss` 純 keyword 防護——偵測 conditions 僅含 keyword 一條時，改用 GPSS 可接受的全文檢索 command 形式（keyword 展開到多欄位 OR，或 GPSS 支援的自由文字 command），使 request 成為有效檢索指令。**驗證前不 commit code 改動。** 修復點：`src/patent_mcp_server/search_dispatcher.py::_run_gpss` line 146-160。

### 檔案整理
- 原 `issues/BR_20260709_search_all_sources_error.md`（open 版）與本檔內容已合併於此，open 版刪除，消除同名重複。
