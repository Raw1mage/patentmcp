# Tasks: mcp_r16-domain-kb

## 1. Server 實作

- [x] 1.1 KB 連線層：`PATENTS_KB_DB` env + URI `mode=ro` + `PRAGMA query_only=ON`；缺檔/未設/不可開 → `KB_UNAVAILABLE` envelope + remedy 欄
- [x] 1.2 `patentmcp_kb_query`（FTS/LIKE/hybrid 三模式 + matchMode 揭露 + type/limit 參數，limit 預設 10 上限 50）與 `patentmcp_kb_get`（單物件全文 + provenance lineage），read-only annotations
- [x] 1.3 判斷密集工具 description 加 `consider: patentmcp_kb_query`（patent_search / patent_bulk / pool_fetch / gpatents_get / ppubs_batch_get_claims，≥5 個）

## 2. 掛載與 manifest

- [x] 2.1 docker-compose.yml 加 `./.specbase:/var/lib/patentmcp/kb` bind mount + `PATENTS_KB_DB=/var/lib/patentmcp/kb/ragbase.sqlite` env
- [x] 2.2 mcp.json instructions 加 KB signpost 句 + version 0.4.0→0.5.0
- [x] 2.3 patentworks SKILL.md 加 recall-first 紀律句（R15 guide 同步生效）

## 3. 測試與驗證

- [x] 3.1 `tests/test_kb_tools.py`：FTS 命中既有物件 / 短 token like-scan matchMode / 缺檔 KB_UNAVAILABLE / query_only 生效（寫入應失敗）/ 空 query 拒絕 / type+limit 過濾
- [x] 3.2 既有測試套件無回歸（pytest 全套）
- [x] 3.3 live MCP smoke：容器 restart 後由 MCP rail 呼叫 kb_query（"GPSS API" 命中）+ 兩門一致性（gate.ts 同 query 同 id 集合）
- [x] 3.4 event_record 收尾 + CHANGELOG + specs/architecture.md 同步（新 KB serving 邊界）+ 上游 standard §12 matrix 待補註記
