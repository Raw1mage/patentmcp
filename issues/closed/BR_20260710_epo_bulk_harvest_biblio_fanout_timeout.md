# BR: EPO 全撈逐件 biblio fan-out 逾時（epo_bulk_harvest 熱補丁待固化）

- 日期：2026-07-10
- 類型：bug report + 新工具（已熱補丁，待正式歸檔 + 測試）
- 元件：`patent_search` EPO 分支 biblio fan-out / 新增 `epo_bulk_harvest`
- 提出脈絡：AIOT 非接觸異常偵測 EPO v2 建池全撈

## 問題

用 `patent_search` 對 EPO 單發 `num=2000` 做全撈必逾時：EPO OPS search 只回
公開號清單，書目（biblio）要**逐件 fan-out** 二次查詢（受 15/min 節流）。
1861 筆逐件 biblio ≈ 54s+，遠超 MCP 單次 tool call timeout，整發失敗、零落地。

## 根因

`patent_search` 的 EPO 分支是「search → 逐件 biblio」**同步二段**，大 num 時
fan-out 階段時間爆炸，且**全撈完才落地**（all-or-nothing），逾時 = 全丟。

## 已做的熱補丁（待正式化）

新增 `epo_bulk_harvest` MCP tool（`patents.py`）：**per-page absorb**——
撈一頁（num≈20-100）就 COALESCE upsert 進 patentdb，撈一頁存一頁，
不等全撈完。實證：num=20 穩定、per-page 落地可驗證，繞過單發逾時。
配合 date 切片，6 切片全撈成功落地（EP 151 / WO 233 + CN/US 混入）。

## 待補（本 BR 未完成部分）

1. **新工具未進正式 API 契約**：`epo_bulk_harvest` 是臨時造的，參數/回傳/錯誤碼
   沒有比照 `patent_bulk_export` 的正式契約文件，KB 來源梯也沒收錄。
2. **與 patent_bulk_export 語義重疊未釐清**：兩者都是「窮盡批次」，應明確
   分工（bulk_export=GPSS 分類軸 / epo_bulk_harvest=EPO 全球公開號），
   或合併成單一 bulk 入口依 source 路由。
3. **無測試**：per-page absorb 的冪等性（COALESCE upsert 重跑不覆寫）、
   斷點續撈沒有測試覆蓋。
4. **節流未內建自適應**：15/min 節流靠 date 切片人工繞，未內建 rate-limit
   backoff。

## 驗收

- `epo_bulk_harvest` 有正式契約文件 + KB 來源梯收錄。
- 與 `patent_bulk_export` 分工釐清（或合併）。
- per-page 冪等 + 斷點續撈有測試。

---

## 結案記錄 2026-07-10(plan `patentmcp_bulk-entry-unification`)

依使用者決策,`epo_bulk_harvest` 未分立正式化,而是**合併進單一 bulk 入口 `patent_bulk(source="gpss"|"epo")`**:

- **契約正式化**:`patent_bulk` MCP docstring 為正式契約(source 顯式選源、兩源額度/節流差異、per-page absorb、`next_skip`/`exhausted` 續撈語義);dispatcher 層 `bulk()` 路由(`search_dispatcher.py`),既有 `epo_bulk_harvest` 實作零改動復用。
- **分工釐清**:三舊工具(`patent_bulk_export`/`patent_bulk_harvest`/`epo_bulk_harvest`)→ `TOOL_RENAMED` stub(`use:"patent_bulk"`),語義重疊問題以合併終結。
- **測試**:`tests/test_patent_bulk.py` 覆蓋路由四向、per-page absorb(每頁 callback、callback raise 不中斷)、next_skip 續撈、三舊工具 stub;全套件 175 passed。
- **KB 收錄**:SKILL.md §5 bulk 條目改寫 + priorsearch.md 同步。
- **待補 4(節流自適應 backoff)**:OUT-OF-SCOPE,維持 date 切片人工繞;需要時另立 issue。

Status: **Resolved**
