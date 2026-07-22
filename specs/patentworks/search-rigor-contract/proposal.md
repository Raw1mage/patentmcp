# Proposal: patentworks_search-rigor-contract

## Why

patentworks 的 `priorsearch` flow 重複發生同一類問題：**工作流明明有寫的要求，重做報告時卻不遵守**。具體症狀（使用者 2026-06-28 親述）：

- 檢索應該用多參數 AND/OR 排列組合反覆嘗試 → 實際只檢幾條就交差。
- 應配合 UPC（USPC）等分類做範圍限縮 → 實際完全沒做。
- 整份報告檢索強度嚴重不足，但仍通過了所有既有檢查、產出了「看起來完整」的交付物。

根因不在執行者偷懶，而在 **skill 本身缺乏可驗證的檢索強度契約**：所有現行檢查都驗「輸出產物品質」（CSV 件數、欄位、分佈），**沒有任何一道閘驗「檢索過程強度」**。因此一個薄檢索只要湊出乾淨的 20 列 CSV，就能合法通過——字面上不違反任何規範。

## Original Requirement Wording (Baseline)

- 「我希望能治本，也就是把 patentworks 工作流寫好寫清楚。很多問題一直在重複發生。明明工作流有講的，重新做一份報告時卻不遵守。例如檢索要多參數 and/or 排列組合去嘗試，要配合 UPC 來限縮範圍，這次的報告都沒有做到，隨隨便便檢了幾條就交差。」

## Requirement Revision History

- 2026-06-28: 初始提案，鎖定「檢索強度契約 + 統一資料樹」雙根因。

## Effective Requirement Description

1. 為 `priorsearch` flow 的「完整檢索矩陣」建立**可數、可機檢**的最低強度契約（最少分類錨點數 × 最少關鍵字概念群 × 必跑三地 × AND/OR 組合展開）。
2. 把 USPC/UPC 從「隱性欄位」提升為**一級限縮軸**，與 IPC/CPC 並列寫入檢索矩陣與報告復現章。
3. 在 patentmcp 新增一個 **machine-checkable 閘工具 `search_audit`**：讀 `matrix-log`，機檢矩陣覆蓋率與筆數，不達門檻回 `FAIL`，使 AI 無法以薄檢索交差（這是治本的力道來源）。
4. 統一 `SKILL.md` 與 `priorsearch.md` **互相矛盾的資料樹規範**，消除「同一案長出兩套平行管線」的結構病灶。

## Scope

### IN

- patentmcp 新增 `search_audit` 工具（`matrix-log` schema parser + 覆蓋率機檢 + PASS/WARN/FAIL envelope）。
- 改寫 `priorsearch.md`：矩陣最低維度契約、`matrix-log` 強制 schema、§3.B 複核閘改為「先數矩陣覆蓋率再看池子」、USPC 升一級軸、新增 `search_audit` 為交付前強制閘。
- 統一 `SKILL.md §Data Tree` ↔ `priorsearch.md §0` 為單一資料樹真相。
- republish skill 到 XDG projection。

### OUT

- 報告章節重寫、PDF/圖降級路徑、token 紀律。
- 其他 flow（disclosure / screening / analysis / drafting）的內容改寫——僅在資料樹統一處連帶觸及 screening 的目錄引用。
- **不回頭重做 TWCID 既有報告**（那是已 verified 的交付；本案是工具治本，不溯及既往產物）。

## Non-Goals

- 不追求「自動跑檢索」——人類複核裁決仍是專利工作的鐵則。
- 不把 `search_audit` 做成會自己發查詢的東西；它只稽核「已留下的 matrix-log 證據」，不執行檢索。

## Constraints

- `search_audit` 只稽核**證據**（matrix-log），不在 server 端代跑檢索（維持「AI 留證據、工具驗證據」分工，避免重造爬蟲/查詢輪子）。
- 門檻數值必須有依據（可調、可解釋），不得是魔術數字；FAIL 訊息要明確指出缺哪一軸。
- 改 SSOT（`/home/pkcs12/projects/patentmcp/skills/patentworks/`），不直接改 XDG projection（會被 republish 覆寫）。
- 既有 27 個工具與註冊機制（`patents.py` FastMCP `@mcp.tool()`）不破壞；新工具比照 `screening_table.py` 的 server-side 落地範本。

## What Changes

- `src/patent_mcp_server/`：新增 `search_audit.py` 模組（純函式 schema parser + 覆蓋率計算），`patents.py` 加一個 `@mcp.tool() search_audit(...)` 薄包裝。
- `skills/patentworks/flows/priorsearch.md`：強度契約 + matrix-log schema + 複核閘改寫 + USPC 升軸 + search_audit 強制閘。
- `skills/patentworks/SKILL.md`：Data Tree 統一。
- XDG projection republish。

## Capabilities

### New Capabilities

- `search_audit`：讀 matrix-log，機檢「分類錨點數 / 關鍵字概念群數 / 三地覆蓋 / AND-OR 組合展開 / USPC 是否入軸 / 最低查詢筆數」，回 PASS/WARN/FAIL + 缺口清單。交付前強制閘。

### Modified Capabilities

- `priorsearch` flow：從「散文願望式檢索」升級為「可機檢強度契約」；複核閘語意從「池子整不整齊」改為「先驗檢索夠不夠廣、再驗池子品質」。

## Impact

- 受影響：patentmcp server 工具集（+1）、patentworks skill（priorsearch.md / SKILL.md）、XDG skill projection、所有未來走 priorsearch 的檢索任務。
- 不受影響：既有 TWCID 交付物、其他四個 flow 的核心內容、既有 27 工具行為。
