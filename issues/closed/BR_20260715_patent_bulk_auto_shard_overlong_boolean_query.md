# BR_20260715_patent_bulk_auto_shard_overlong_boolean_query

- **Status**: Resolved (2026-07-15)
- **Severity**: high（逼使用者手動拆片、污染方法論可復現性、且拆錯 D 會漏排）
- **Component**: `patent_bulk` / `patent_search`（GPSS 分支）· query 組裝層
- **Reporter**: anomaly-noncontact-priorart 案（DD-42 重建實撈實戰）
- **Related**: BR_20260710_patent_bulk_epo_mcp_timeout_no_resume（同屬 bulk 韌性）

## 症狀（實證，2026-07-15 DD-42 重建實撈）

大型 landscape 檢索的召回式是「(技術手段 OR 群 ~45 詞) AND (情境功效 OR 群 ~50 詞) NOT (工業雜訊 OR 群 ~50 詞)」。這種 recall-first 長 query 撞**兩道獨立的牆**：

| | 牆 A：MCP/HTTP 傳輸層 | 牆 B：GPSS 後端 |
|---|---|---|
| 症狀 | `patent_search`(GET) → HTTP 414 URL too long | `patent_bulk` → `GPSS_ERROR: Exceeded search condition length` |
| 誰拒絕 | MCP HTTP GET 塞不下長 URL | GPSS 伺服器自身檢索條件字串長度上限 |
| POST 能否救 | ✅ 改 POST body 可解 | ❌ 不可，上游硬限制 |

本案 12 片實撈中，**牆 B 逼使用者做兩種手動降級**：
1. **拆正向群**：TW/US 的 B2(38-45詞) 整組撞牆 → 手動對半拆 B2a(光學視覺)/B2b(聲學生理)，跑兩條子查詢再 union。
2. **砍 NOT 群**：US 完整 D(50詞含車輛自駕) 撞牆 → 被迫縮短為 D-1(26詞工業種子)，車輛自駕 16 詞退離線標記 → **三國 D 不對稱，precision 基準漂移**。

## 根因

query 組裝層把「使用者給的 recall-first 長布林式」**原樣單發**給 GPSS，超過後端 condition-length 上限就 fail-fast 丟 `GPSS_ERROR`，把「如何在不犧牲 recall 的前提下切分」的責任丟回呼叫端（AI/使用者）。手動切分的三個代價：
- **可復現性破損**：一條邏輯檢索式變成 N 條物理子查詢散在對話裡，領域鐵律「檢索式即命脈、逐條落檔可復現」被稀釋。
- **拆錯 D 的正確性風險**：呼叫端在壓力下可能拆 NOT 群——`¬D` 拆成 `¬D1 ∪ ¬D2` 在集合論上**不等價**（`¬(D1∪D2) = ¬D1 ∩ ¬D2`），會漏排雜訊。
- **工作流瓶頸**：每個大 landscape 案都要人肉拆片，量越大拆越多。

## 修復設計（工具層自動分片，recall-preserving）

`patent_bulk`（及 `patent_search` GPSS 分支）在偵測到 `Exceeded search condition length` 時，**自動分片重試**，對呼叫端透明地回傳單一 union 結果：

1. **只拆正向 AND 群，絕不拆 NOT 群**（正確性硬約束）：
   - query 結構已知為 `(A) and (B) and (C) not (D)`（GPSS 欄內中綴語法）。
   - 二分**最長的正向 OR 群**（B 或 C，取詞數最多者）為兩半 `Bx`/`By`。
   - 數學保證等價：`(Bx∪By) ∩ C ¬D = (Bx∩C¬D) ∪ (By∩C¬D)`（交集對聯集的分配律）。
   - **D（NOT 群）在每個子查詢中原樣保留、完整不動**——這是 recall/precision 正確性的前提。
2. **遞迴分片**：若子查詢仍超長，繼續二分（比照 EPO slice_plan 的遞迴二分），直到每片落在 condition-length 內。
3. **pubno union 去重**：各子查詢 records 以 pubno 為 key 聯集去重，per-page absorb 照舊落 patentdb。
4. **透明回傳**：envelope 回單一結果集 + `sharding: {applied: true, shards: [{query_frag, total, landed}], union_total, union_landed}` 供稽核（呼叫端看到的是「一條 query 的完整結果」，但可稽核它內部拆了幾片）。
5. **fail-fast 邊界**：若連「單一 OR 詞 + 全 AND/NOT」都仍超長（極端），才回 `CONDITION_LENGTH_IRREDUCIBLE` 要求呼叫端縮詞。

## 驗收

- 給一條 B(45)∩C(50)¬D(50) 的長 query（現況必撞牆），`patent_bulk` 回 `success:true` + `sharding.applied:true`，union_total 與「手動拆 B2a/B2b union」結果一致（pubno 集合相等）。
- D 群在每個 shard 的 XML/query body 中逐字完整（機檢：每 shard 的 not(...) 段 byte-identical）。
- 遞迴分片對 triple(A∩B∩C¬D) 與 pairwise(B∩C¬D 無 A) 都適用。

## 暫行 workaround（本案已用，待工具修好後移除）

手動拆 B2a/B2b + US 側縮短 D-1（車輛自駕退離線標記），逐片落 `pool_membership_dd42.jsonl` + `query_provenance_dd42.json`（含 `d_note` 記錄 D 不對稱）。這是可復現的暫行解，但正是本 BR 要從工作流消除的手動負擔。

## Resolution (2026-07-15)

owning spec `patentmcp_bulk-entry-unification` extend（DD-10/DD-11、Phase 8）。

**先釐清使用者疑問——POST 實測封死（DD-10）**：曾疑「長 payload 改 POST 放 body 可繞 URL 長度牆」，對 `tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api` 做對照探測：(A)POST 空請求→`usage:...`(38B)；(B)POST userCode 只在 body→`usage:...`(38B，**==A**)；(C)POST userCode 在 URL→`userCode not exist`(96B)；(D)GET 同 C。**B==A 且 C==D → GPSS 後端只讀 URL query string，POST body 一律忽略**。故傳輸手段無法繞牆，分片是唯一解（且一石二鳥：拆短同時過 URL 414 + condition length）。

**實作（DD-11，全自動工具層分片）**：`search_dispatcher.py` 新增純函式 `_parse_gpss_query`/`_shard_gpss_query`（只二分詞數最多的**正向** OR 群，NOT 群每 shard **byte-identical** 完整保留，遞迴二分深度 cap 6，不可再分→`CONDITION_LENGTH_IRREDUCIBLE`）；`bulk_harvest` 偵測 condition-length marker → `_bulk_harvest_sharded`（逐 shard 走既有 `_bulk_pull_gpss_kw`、pubno union 去重、envelope 補 `sharding:{applied,shards[],union_total,union_landed}`）。未撞牆路徑行為不變。

**驗證**：`tests/test_gpss_query_slice.py` 9 passed（含 NOT 群 byte-identical 不變量專測）；全套件 210 passed 0 fail（基線 187，零回歸）。orchestrator 獨立跣測驗證（非信任 subagent 自報）。

**限制**：`_GPSS_CONDITION_LENGTH_LIMIT=900`（TIPO byte 上限不透明，保守估）+ shard 實擈仍撞牆則 fail-fast（belt-and-suspenders）；日後可依實測收斂。
