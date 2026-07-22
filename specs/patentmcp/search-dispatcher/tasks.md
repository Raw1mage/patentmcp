# Tasks: patentmcp_search-dispatcher

## 1. Dispatcher 核心

- [x] 1.1 新增 `src/patent_mcp_server/search_dispatcher.py`:QuerySpec 正規化 + `AXIS_CAPABILITY` 矩陣 + 來源梯路由(GPSS→EPO→PPUBS→gated gpatents)+ ProvenanceEntry 組裝(schema 見 data-schema.json)
- [x] 1.2 screening_table.py 新增 `ppubs_to_records`(PPUBS 原生 JSON → 統一 record)與 EPO biblio 映射(search→biblio 二段 → 統一 record)
- [x] 1.3 patents.py 新增 `@mcp.tool() patent_search`(統一參數 + allow_scraping=False 預設),內部呼叫 dispatcher;回傳 PatentSearchEnvelope

## 2. 舊工具下架

- [x] 2.1 移除 `gpss_search` / `epo_search` / `gpatents_search` 的 `@mcp.tool()` 裝飾器,函式本體改名 `_gpss_search_impl` 等內部函式;grep 全倉引用點修正(`patent_get_claim1`、`fetch_patent_pdf` 等)
- [x] 2.2 `uspto_patents` 移除 search 類 method(`ppubs_search_patents`/`ppubs_search_applications`):dispatch 表拒收並回結構化錯誤指引 `patent_search`;docstring 同步縮減
- [x] 2.3 `build_screening_table` 內部改接 dispatcher(保持對外回傳格式不變;gpatents 級受 allow_scraping 閘)

## 3. 測試

- [x] 3.1 新增 `tests/test_search_dispatcher.py`(monkeypatch clients,不打真網路):GPSS 首選命中、GPSS 未 configured 降級 EPO、USPC 軸直達 PPUBS、SCRAPING_REQUIRED 閘、allow_scraping=True 尾級放行、provenance 完整性、ALL_SOURCES_MISS(test vectors 見 test-vectors.json)
- [x] 3.2 既有測試套件全綠(`pytest tests/`);`build_screening_table` 相關測試(P7)按新路徑修正

## 4. 標準面同步(mcp integration standard)

- [x] 4.1 `mcp.json`:version 0.2.3→0.3.0(R5.1),instructions 重寫宣告單一檢索入口與來源梯內建語義(R3/R13.5)
- [x] 4.2 README:檢索工具章節改寫 + 舊工具→dispatcher 遷移對照表
- [x] 4.3 skill 文件同步:`skills/patentworks/SKILL.md` §5(來源梯改為 dispatcher 內建行為)、`flows/screening.md`、`flows/priorsearch.md`、`skills/patent-practitioner-workflow.md`——舊檢索工具名全數清除
- [x] 4.4 `webctl.sh refresh` 後 live 驗證:`GET /tools` 只含 `patent_search` 一個檢索工具;landing page 一致

## 5. 收尾

- [x] 5.1 `specs/architecture.md` 全貌同步(檢索表面章節改寫)
- [x] 5.2 event_record 收尾(Key Decisions / Verification / Friction)+ README 更新(repo 無 CHANGELOG.md,依規範更新 README 即可;push 前再補)
