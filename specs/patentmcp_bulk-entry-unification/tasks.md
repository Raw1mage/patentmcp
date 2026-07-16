# Tasks: patentmcp_bulk-entry-unification

## 1. Dispatcher 統一路由

- [x] 1.1 `search_dispatcher.py` 新增 `bulk(spec, source, *, gpss_client, epo_client, absorb_cb)`:source 驗證(INVALID_PARAMS fail-fast)+ 路由到既有 bulk_export/bulk_harvest/epo_bulk_harvest
- [x] 1.2 GPSS 側 envelope 補 `next_skip`/`exhausted`(對齊 EPO 續撈語義,DD-3)

## 2. MCP 工具層

- [x] 2.1 `patents.py` 新增 `patent_bulk` MCP 工具(完整 docstring 契約:source 語義、兩源額度/節流差異、續撈用法、DD-2 keyword 防呆提示)
- [x] 2.2 三舊工具(patent_bulk_export/patent_bulk_harvest/epo_bulk_harvest)改為 TOOL_RENAMED stub,note 帶參數搬遷指引

## 3. 測試固化

- [x] 3.1 `tests/test_keyword_to_cql.py`:布林/片語/括號/NOT 四類 + 空字串/純片語 edge
- [x] 3.2 `tests/test_patent_bulk.py`:路由四向(gpss-export/gpss-harvest/epo/invalid source)+ 三舊工具 stub 斷言
- [x] 3.3 EPO per-page absorb 測試:每頁 callback 觸發、absorb 例外不中斷、next_skip 續撈、COALESCE 冪等(重跑不覆寫)
- [x] 3.4 全套件回歸:`pytest tests/` 零 fail

## 4. KB / skill 同步

- [x] 4.1 SKILL.md §5:bulk 條目改寫為 `patent_bulk` 統一入口契約(含兩源選源決策表、續撈語義、額度硬閘連動)
- [x] 4.2 SKILL.md §5 EPO 條目補註:patent_search EPO 分支與 patent_bulk(source=epo) 支援布林 keyword(AND/OR/NOT/引號片語/括號)

## 5. BR_20260628 驗證 B

- [x] 5.1 驗證 delegation-clauses runtime 注入端到端:pin patentworks → 委派取圖子代理(prompt 不手抄條款)→ 斷言子代理 prompt 含注入區塊且行為走窮舉

## 6. 收尾

- [x] 6.1 三張 BR 補結案記錄並移至 issues/closed/(BR_20260628 若驗證 B 未過則留 REOPENED 並記錄阻塞)
- [x] 6.2 specs/architecture.md 同步(bulk 工具面變更)
- [x] 6.3 event log 收尾 + ragbase distill 判斷

## 7. EPO auto date-slicing(revise 2026-07-10,DD-8/DD-9)

- [x] 7.1 `search_dispatcher.py` 新增 `epo_slice_plan(spec, epo_client)`:count-probe 取母數、遞迴二分 date 區間(互斥切點)、深度 cap 6/probe cap 32、sum_check(5% 容忍)、SLICE_INEFFECTIVE/DATE_RANGE_REQUIRED fail-fast、觸頂片 truncated 標記
- [x] 7.2 `patents.py` `patent_bulk` 新增 `slice_plan: bool = False` 參數(planning-only 呼叫,零 records/零 absorb),docstring 補切片工作流(plan → 逐片呼叫 → 片內 next_skip 續撈)
- [x] 7.3 測試 `tests/test_epo_slice_plan.py`:單片(total≤wall)/二分遞迴(各片<wall)/DATE_RANGE_REQUIRED/SLICE_INEFFECTIVE/深度 cap 觸頂 truncated/probe cap;Fake EPO client 可控 total 分佈
- [x] 7.4 全套件回歸零 fail
- [x] 7.5 SKILL.md §5 EPO bulk 條目補 slice_plan 工作流;收搜 issue_20260710_epo_bulk_auto_date_slicing 至 closed/

## 8. GPSS query-slicing 全自動分片(extend 2026-07-15,DD-10/DD-11,BR_20260715)

- [x] 8.1 `search_dispatcher.py` 新增 GPSS 布林式 parser + 分片器:解析 keyword 為頂層 AND 群(正向 OR 群 vs NOT 群)、選詞數最多正向群二分(`Bx`/`By`)、NOT 群原樣保留、遞迴二分(深度 cap 6)、CONDITION_LENGTH_IRREDUCIBLE fail-fast。純函式(不打網路),可單獨測試
- [x] 8.2 `bulk_harvest` 偵測 `Exceeded search condition length` → 觸發自動分片:逐子查詢 `_bulk_pull_gpss_kw` → pubno union 去重 → envelope 補 `sharding:{applied,shards[],union_total,union_landed}`
- [x] 8.3 `patent_bulk` docstring 補 GPSS 自動分片說明(對呼叫端透明、sharding 稽核欄、IRREDUCIBLE 邊界)
- [x] 8.4 測試 `tests/test_gpss_query_slice.py`（9 pass / 0 fail）:parser 布林/片語/括號/NOT、最長群選取、遞迴二分、**NOT 群每 shard byte-identical**、union 去重、IRREDUCIBLE fail-fast、三國對稱性(A∩B∩C¬D 與 B∩C¬D 皆適用)
- [x] 8.5 全套件回歸零 fail（210 passed / 0 fail）
- [x] 8.6 SKILL.md §5 GPSS bulk 條目補自動分片工作流 + 檢索式紀律(勿塞冗詞、優先分類軸);BR_20260715 歸檔 closed/
- [x] 8.7 architecture.md 同步(GPSS query-slicing);idef0/grafcet 分片節點更新
