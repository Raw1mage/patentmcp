# Proposal: mcp_r16-domain-kb

## Why

- patentmcp 的領域知識庫（ragbase KB，`.specbase/ragbase.sqlite`，21 筆 evidence-graded 物件：GPSS API 規格、前案檢索方法論 6 concepts、代表圖窮舉梯 workflow、TW 書目補位等 failure-modes、專利分析七段式方法論）目前只存在 host-side，唯一讀取路徑是 specbase `gate.ts ragbase_query`（需要 host 檔案系統 + bun）。
- **patentmcp 的用戶——透過 MCP 驅動 `patentmcp_*` 工具的 agent（含遠端 TCP :8000 client）——完全查不到這個 KB**。服務要求專利實務判斷（檢索式設計、來源梯判讀、screening 尺度），卻不供給支撐判斷的領域記憶。
- 上游標準已就位：mcp-integration-standard **R16 Domain-KB self-shipping**（2026-07-11 extend）規定 expert-domain MCP MUST 自帶 in-band queryable domain KB；patentmcp 被點名「follows once its corpus exists」——corpus 已存在，義務生效。
- Reference impl 已落地：bodesign（`bodesign_kb_query`/`kb_get`，2026-07-11 verified）。本 plan 是同 pattern 的 patentmcp 採納。

## Original Requirement Wording (Baseline)

- 「根據mcp integration standard spec最新指引，把查詢知識的工具實作出來」（2026-07-11）

## Requirement Revision History

- 2026-07-11: initial draft created via plan-init.ts；scope 定為 R16 adopter（標準條文與 reference impl 皆已在上游落地；本 plan 只做 patentmcp 端實作）

## Effective Requirement Description

1. patentmcp MCP server 新增 `patentmcp_kb_query(q, type?, limit?)` 與 `patentmcp_kb_get(id)` 兩個 read-only 工具，對 repo 的 ragbase KB 做確定性檢索（FTS/BM25 + 短 token LIKE fallback，比照 specbase / bodesign 查詢語義），任何 MCP client（UDS 或 TCP）皆可呼叫。
2. KB store 掛載進容器；serving 端 application-level 唯讀（R16.4：無 KB-write MCP 工具；寫入唯一路徑仍是 host-side specbase producer.ts）。
3. Recall-first signpost（R16.5）：`mcp.json` instructions 加一句 KB 宣告；R15 guide（patentworks SKILL.md 投影）納入 recall-first 紀律；判斷密集工具 description 加 `consider: patentmcp_kb_query`。
4. 查詢降級自述（R16.6）：payload 揭露 matchMode（fts / like-scan / hybrid）；KB 檔缺失 → typed `KB_UNAVAILABLE` fail-fast，不回靜默空結果。

## Scope

### IN
- `src/patent_mcp_server/patents.py`：兩個 `@mcp.tool` + KB 連線層（stdlib sqlite3）
- `docker-compose.yml`：`.specbase/` 掛載 + `PATENTS_KB_DB` env
- `mcp.json` instructions signpost + 版本 bump
- `skills/patentworks/SKILL.md`（= R15 guide 單一來源）recall-first 段
- 判斷密集工具 description 的 `consider:` affordance
- pytest（查詢語義 + fail-fast + read-only 驗證）

### OUT
- KB 內容擴充（另有蒸餾工作流）
- KB 寫入工具（R16.4 明確禁止）
- specbase 端任何變更
- gateway / web 面

## Non-Goals

- 不做 LLM re-ranking / semantic embedding（R16.2 deterministic serving）
- 不做 KB 同步/複製（R16.7 one-KB-two-doors：同一個 sqlite 檔，兩個門）

## Constraints

- Container-side pure-python；sqlite3 stdlib 即可，不引入新依賴
- 天條 1：KB 不可用 → fail fast 顯式報錯（typed envelope），不靜默續跑
- WAL store：host 端 producer 用 WAL 寫入；容器讀取需能建 `-shm`/`-wal` side files → 掛載目錄 rw、application 層 `mode=ro` + `PRAGMA query_only` 強制唯讀（design DD-3）
- 錯誤面沿用 patentmcp 既有 `{"success": False, "error_code": ...}` envelope 慣例（非 bodesign 的 raise-typed-error）

## What Changes

- patentmcp MCP tool 數 36 → 38（`patentmcp_kb_query`, `patentmcp_kb_get`）
- 容器新增 `./.specbase:/var/lib/patentmcp/kb` bind mount + `PATENTS_KB_DB` env
- `mcp.json` instructions 增 KB signpost 段 + version 0.4.0 → 0.5.0
- patentworks SKILL.md（R15 doctrine 源）增 recall-first 紀律句

## Capabilities

### New Capabilities
- `patentmcp_kb_query`: 對 ragbase KB 做確定性全文檢索，回傳 evidence-graded 知識物件（id/type/title/score/confidence/source_weight + matchMode）
- `patentmcp_kb_get`: 取單一知識物件全文（body_md + provenance lineage）

### Modified Capabilities
- 判斷密集工具（patent_search / patent_bulk / pool_fetch / gpatents_get / ppubs_batch_get_claims）description：加 `consider: patentmcp_kb_query` recall-first affordance

## Impact

- `src/patent_mcp_server/patents.py`（KB 連線層 + 兩個 tool）
- `docker-compose.yml`（掛載 + env）
- `mcp.json`（instructions + version）
- `skills/patentworks/SKILL.md`（recall-first 段；R15 guide 同步生效——doctrine per-request 讀取，零 rebuild）
- `tests/test_kb_tools.py`（新測試模組）
- 上游 spec：`opencode/specs/mcp-integration-standard` §12 R16 adoption matrix（patentmcp 條目待標 done）
