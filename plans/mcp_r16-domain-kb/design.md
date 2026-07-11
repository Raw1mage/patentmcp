# Design: mcp_r16-domain-kb

## Context

patentmcp 是 expert-domain MCP（專利實務），mcp-integration-standard R16（2026-07-11 extend）規定此類服務 MUST 自帶 in-band queryable domain KB；bodesign 已為 reference impl（`bodesign/plans/mcp_r16-domain-kb/`，verified）。KB 實體已存在：`.specbase/ragbase.sqlite`（specbase ragbase schema：`ragbase_objects` + FTS5 trigram `ragbase_fts` + `ragbase_lineage` 邊），21 筆 evidence-graded 專利實務知識（GPSS API 規格 verified、前案檢索方法論 6 concepts、figure-exhaustion-ladder workflow、2 筆 failure-modes）。缺的只是「容器內的門」：server 端查詢工具 + 掛載 + signpost。

## Goals / Non-Goals

**Goals**

- 任何 MCP client 可查 ragbase KB（R16.2）
- 唯讀 serving、fail-fast、降級自述（R16.4/16.6、天條 1）
- 與 host-side gate.ts 同 store 無 fork（R16.7）
- recall-first signpost 全就位（R16.5 a/b/c 三軌）

**Non-Goals**

- KB 寫入工具、KB 內容擴充、LLM 排序、scope 過濾策略

## IDEF0-first skeleton

架構掛在 `idef0.json` A0 分解上：**A1 Serve KB Query**（FTS/LIKE/hybrid 查詢規劃 + matchMode 揭露）→ DD-2；**A2 Serve KB Get**（單物件全文 + provenance）→ DD-2；**A3 Guard Read-Only Access**（ro 連線 + fail-fast envelope）→ DD-3/DD-4/DD-6；**A4 Signpost Recall-First**（instructions + SKILL.md doctrine + consider: affordance）→ DD-5。A1/A2 的 mechanism 來自 A3 的唯讀連線；A4 是部署面前置（grafcet step 6）。

## Decisions

- DD-1（照抄 bodesign reference impl 的檢索核心，錯誤面轉 patentmcp 慣例）：查詢規劃（`_kb_match_plan`）、LIKE escape、source_weight lineage 聚合直接移植 bodesign `services/mcp/server.py` L789-957（R16 reference impl，已 verified）。差異只在錯誤面：bodesign 用 raise KbError → run_tool 轉 isError；patentmcp 的 FastMCP 工具一律回 dict envelope，故 KB 錯誤回 `{"success": False, "error_code": "KB_UNAVAILABLE", "message": ..., "remedy": ...}`（比照 cache_* 工具的 OWNER_REQUIRED / EXPORT_TARGET_UNREACHABLE 慣例）。
- DD-2（查詢語義比照 specbase，不重造）：trigram tokenizer 的 ≥3 碼點限制照 specbase gate.ts plan 邏輯：全 token ≥3 → FTS `AND`；全 <3 → LIKE scan over title/body（score=0、按 recency）；混合 → hybrid。payload 必帶 `matchMode`（R16.6 自述義務，防 CJK 短查詢靜默 0-hit 假象）。SQL 對象是 ragbase 實際表（已 `.schema` 對齊：`ragbase_objects`/`ragbase_fts`/`ragbase_lineage`，欄位 id/type/title/confidence/body_md/updated_at/…）。
- DD-3（WAL 唯讀策略：目錄 rw 掛載 + 連線層強制唯讀）：host producer 以 WAL 寫入；sqlite 讀 WAL DB 需要能建 `-shm`/`-wal` side files，純 ro bind mount 會 `SQLITE_CANTOPEN`；`immutable=1` 有並行寫入者時讀 stale/torn——不合格。故：**目錄 rw 掛載（`./.specbase:/var/lib/patentmcp/kb`），唯讀在 application 層強制**（URI `mode=ro` + `PRAGMA query_only=ON`，per-request 連線），MCP surface 零寫入工具。拒絕方案：ro mount（WAL 讀不了）、immutable（資料完整性）、複本同步（R16.7 fork 禁令）。
- DD-4（fail-fast typed envelope）：KB 檔缺失/env 未設/不可開 → `error_code: KB_UNAVAILABLE` + `remedy` 欄（指向 host-side `producer.ts ragbase_distill`；mount is live，no restart needed）。絕不回空 hits 假裝無知識（天條 1 / R0.5 error affordance）。
- DD-5（signpost 三軌）：(a) mcp.json instructions 加 KB 宣告句（R16.5a）；(b) patentworks SKILL.md（= R15 `patentmcp_init` doctrine 單一來源，per-request 投影）加 recall-first 紀律——SKILL.md 一改，guide 面即時生效，零 rebuild（R15 live-reload 既有機制）；(c) 判斷密集工具（patent_search / patent_bulk / pool_fetch / gpatents_get / ppubs_batch_get_claims）description 尾加 `consider: patentmcp_kb_query`（R16.5c）。
- DD-6（env 定位，不 hardcode）：`PATENTS_KB_DB` env 指 KB 路徑（compose 設 `/var/lib/patentmcp/kb/ragbase.sqlite`）；未設時工具回 `KB_UNAVAILABLE`（顯式），不猜路徑。命名沿 patentmcp 既有 `PATENTS_*` env 慣例。

## Risks / Trade-offs

- rw mount 理論上允許容器寫 KB — mitigation：server 程式無任何寫路徑 + query_only pragma；R12.5 turnstile 不需要（工具面唯讀）。
- host WAL 寫入與容器讀並行 — sqlite WAL 支援多讀者單寫者跨進程；bind mount 同 inode，鎖協調安全（bodesign 已驗證同 pattern）。
- FTS schema 與 specbase lib 演進脫鉤 — mitigation：測試直接打真實 repo KB，schema 變更會被測試抓到。
- corpus 尚小（21 筆） — 不影響機制正確性；蒸餾工作流持續補充，KB 門先就位（R16.1 corpus 已非空，非 empty-KB ceremony）。

## Critical Files

- `src/patent_mcp_server/patents.py` — KB 連線層 + `patentmcp_kb_query`/`patentmcp_kb_get`（tool 36→38）
- `docker-compose.yml` — `./.specbase:/var/lib/patentmcp/kb` 掛載 + `PATENTS_KB_DB` env
- `mcp.json` — instructions signpost + version 0.4.0→0.5.0
- `skills/patentworks/SKILL.md` — recall-first 段（R15 guide 同步生效）
- `tests/test_kb_tools.py` — 查詢語義 / fail-fast / 唯讀 / envelope
- `~/projects/opencode/specs/mcp-integration-standard/standard.md` — R16 條文（上游契約，唯讀參照）
- `~/projects/bodesign/services/mcp/server.py` L789-957 — reference impl（唯讀參照）
