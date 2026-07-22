# Spec: mcp_r16-domain-kb

## Purpose

保證 patentmcp 的任何 MCP 用戶（本機 UDS 或遠端 TCP client agent）能在專利工作中以確定性檢索查到 repo 的 ragbase 領域知識庫，且該路徑唯讀、fail-fast、與 host-side specbase 讀取同一個 store——實現 mcp-integration-standard R16 的 patentmcp 採納。

## Requirements

### Requirement: In-band KB query（R16.2）

系統 SHALL 提供 `patentmcp_kb_query(q, type?, limit?)` MCP 工具：對 `.specbase/ragbase.sqlite` 的知識物件做確定性 FTS 檢索（trigram tokenizer；全 token ≥3 碼點走 FTS、全 <3 走 LIKE scan、混合走 hybrid），回傳 `{hits:[{id,type,title,score,confidence,source_weight}], matchMode, total}`；並提供 `patentmcp_kb_get(id)` 回單一物件全文（body_md + provenance）。兩工具皆標註 read-only 語義（readOnlyHint/idempotentHint=true）。

#### Scenario: agent 查 GPSS API 規格

- **WHEN** MCP client 呼叫 `patentmcp_kb_query(q="GPSS API")`
- **THEN** 回傳含 `concept.gpss.api_specification` 的 hits，payload 帶 `matchMode:"fts"`，每筆 hit 帶 confidence 與 source_weight

#### Scenario: 短 CJK 查詢降級自述

- **WHEN** 呼叫 `patentmcp_kb_query(q="檢索")`（全 token <3 碼點）
- **THEN** 走 LIKE scan 並在 payload 明示 `matchMode:"like-scan"`，0-hit 時 caller 可分辨「降級查詢無命中」而非「無知識」

### Requirement: Read-only serving + fail-fast（R16.4 / 天條 1）

serving 端 SHALL 以 `mode=ro` + `PRAGMA query_only=ON` 開啟 KB；MCP surface SHALL NOT 暴露任何 KB 寫入工具。KB 檔不存在或不可開 SHALL 回 typed envelope `{"success": false, "error_code": "KB_UNAVAILABLE", "remedy": ...}`（remedy 指向 host-side 蒸餾路徑），不得回靜默空結果。

#### Scenario: KB 檔缺失

- **WHEN** 容器內 `PATENTS_KB_DB` 指向的檔案不存在（或 env 未設）
- **THEN** `patentmcp_kb_query` 回 `error_code: KB_UNAVAILABLE` + remedy 欄，success=false

### Requirement: One KB, two doors（R16.7）

容器內工具與 host-side `gate.ts ragbase_query` SHALL 讀同一個 `.specbase/ragbase.sqlite`（bind mount，非複本）；同一查詢字串在兩個門的命中物件集合 SHALL 一致（排序分數容許實作差異）。

#### Scenario: 兩門一致

- **WHEN** host 端 `gate.ts ragbase_query --arg q="GPSS"` 與容器內 `patentmcp_kb_query(q="GPSS")` 先後執行
- **THEN** 兩者命中相同 object id 集合

### Requirement: Recall-first signpost（R16.5）

`mcp.json` instructions SHALL 含一句 KB 宣告（查詢工具名 + 何時用）；R15 guide doctrine（patentworks SKILL.md）SHALL 納入 recall-first 紀律；判斷密集工具（patent_search / patent_bulk / pool_fetch / gpatents_get / ppubs_batch_get_claims）的 description SHALL 帶 `consider: patentmcp_kb_query` affordance。

#### Scenario: 冷啟動 agent 發現 KB

- **WHEN** 全新 MCP client 讀取 patentmcp manifest instructions 或呼叫 `patentmcp_init`
- **THEN** 看到 KB 宣告句，知道檢索式設計 / screening 判斷前可先 `patentmcp_kb_query`

## Acceptance Checks

- [ ] `patentmcp_kb_query("GPSS API")` 回傳 ≥1 筆既有蒸餾物件，payload 含 matchMode
- [ ] `patentmcp_kb_get` 回傳 body_md + confidence + provenance
- [ ] 短 token 查詢 payload `matchMode:"like-scan"`
- [ ] KB 檔缺失 → `KB_UNAVAILABLE` envelope + remedy 欄（測試以 env patch 驗證）
- [ ] 兩門一致性：同 query 在 gate.ts 與 MCP 工具命中相同 id 集合
- [ ] MCP surface 無任何 KB 寫入工具；serving connection query_only（寫入嘗試拋錯）
- [ ] instructions 含 signpost；SKILL.md 含 recall-first；≥5 個判斷密集工具 description 帶 consider 行
- [ ] 既有測試套件不回歸；新測試全綠
