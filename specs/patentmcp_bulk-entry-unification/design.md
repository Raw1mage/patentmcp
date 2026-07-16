# Design: patentmcp_bulk-entry-unification

## Architecture (hung on IDEF0 skeleton)

依 `idef0.json` 四個 activity 展開:

- **A1 驗證與路由 bulk 請求** — `search_dispatcher.bulk()`(新增):source∈{gpss,epo} 驗證、該源必要軸驗證、`normalize_query`→QuerySpec、依 source(GPSS 再依 keyword 有無)分派。對應 DD-1/DD-2。
- **A2 GPSS 窮盡拉取** — 既有 `_bulk_pull_gpss`(分類軸 export)/`_bulk_pull_gpss_kw`(keyword 收割),expSkip 自動分頁。零改動復用(DD-7)。
- **A3 EPO 收割與 per-page 落地** — 既有 `_bulk_pull_epo` + `_keyword_to_cql`(熱補丁固化對象),每頁 biblio 完成即 absorb callback 落地(DD-4/DD-6)。
- **A4 組裝統一 envelope** — `_envelope` 超集:`next_skip`/`exhausted` 從 EPO 專屬升為兩源通則(DD-3),`patentdb_absorb` 稽核計數。

## Context

bulk 檢索面現有三個 MCP 工具,語義重疊但後端/節流/續撈語義各異:

| 工具 | 後端 | 軸 | 分頁/續撈 | 落地 |
|---|---|---|---|---|
| `patent_bulk_export` | GPSS | 純分類(keyword 拒收) | expSkip 自動分頁, num≤5000 | 收尾一次 absorb |
| `patent_bulk_harvest` | GPSS | keyword+分類 | expSkip 自動分頁, num≤5000 | 收尾一次 absorb |
| `epo_bulk_harvest` | EPO OPS | keyword(布林→CQL)+分類 | 頁≤100, skip wall 2000, `next_skip`/`exhausted` | **per-page absorb**(biblio fan-out 逾時防丟) |

`epo_bulk_harvest` 與 `_keyword_to_cql` 是 2026-07-10 熱補丁(AIOT EPO v2 建池實戰),已生效但無契約/測試。使用者決策:合併成單一入口。

## Goals / Non-Goals

**Goals**

- 一個 bulk 入口 `patent_bulk`,source 顯式路由,統一 envelope
- 熱補丁行為(per-page absorb、CQL 布林轉譯)有測試鎖定
- 舊工具 typed 轉址,不留 unknown-tool 黑洞

**Non-Goals**

- 跨源自動 fallback(fail-fast 天條)
- EPO 節流自適應 backoff(另案)

## Decisions

- DD-1: **單一入口命名 `patent_bulk`,`source` 為必要參數(`"gpss"|"epo"`),無預設值**。理由:兩後端額度/節流/涵蓋面差異大(GPSS 時段額度 vs EPO 15/min+skip wall),隱式預設會誘發錯後端撞額度;顯式選源 = 顯式成本承諾。拒絕方案:auto-route(違反 no-fallback 天條)、default "gpss"(2026-07-09 額度災難前科)。
- DD-2: **GPSS 分支依 keyword 有無內部二路**:keyword 缺 → `_bulk_pull_gpss`(分類軸全拉,強制全欄 expFld);keyword 給 → `_bulk_pull_gpss_kw`(收割語義)。舊 export「拒收 keyword」的防呆(防過度收窄假零)由 docstring 承接:「拉整軸請勿給 keyword」。
- DD-3: **envelope 統一超集**:兩源都回 `{success, records[], source, provenance[], gaps[], total, next_skip, exhausted, patentdb_absorb, error_code?}`。GPSS 側補算 `next_skip = skip + 已拉筆數`、`exhausted = total 已達或 num 未滿頁`。續撈語義從 EPO 專屬升為契約通則。
- DD-4: **落地策略維持各源既有**:EPO per-page absorb(biblio fan-out 逾時防丟,熱補丁核心);GPSS 收尾 absorb(書目隨頁內建、無 fan-out、逾時風險低)。不強行統一,差異寫進契約文件。
- DD-5: **舊工具 → TOOL_RENAMED stub**(`use: "patent_bulk"`, note 帶參數搬遷指引:舊參數原樣搬 + `source` 補上),沿 BR_20260706 `_TOOL_RENAMED_ENVELOPE` 模式一個 release cycle。
- DD-6: **`_keyword_to_cql` 現行為即契約**:布林運算子小寫化、引號片語保留單一 `txt="..."` term、括號透傳、NOT 轉 `not`。測試鎖布林/片語/括號/NOT 四類 case;若發現巢狀括號/NOT 轉譯錯誤,修函式而非遷就。
- DD-7: **dispatcher 層函式保留不動**(`bulk_export`/`bulk_harvest`/`epo_bulk_harvest`),新 `bulk()` 只做路由;既有 dispatcher 測試零改動,打擊半徑收在 MCP wrapper 層。
- DD-8(revise 2026-07-10): **EPO auto date-slicing = 「slice planning + 片內續撈」,不是單呼叫全拉**(issue_20260710_epo_bulk_auto_date_slicing)。母數 22k 級全拉受 15/min 節流物理上不可能在單次 MCP 呼叫完成,故分兩面:(a) **slice planning**——新增 dispatcher 函式 `epo_slice_plan(spec, epo_client)`:count-probe(num=1 search 只取 total,零 biblio fan-out)取母數;total ≤ wall → 單片;total > wall 且有 date 範圍 → 遞迴二分 date 區間至每片 total < wall,回 `{total, slices:[{date_from, date_to, total}], sum_check}`;(b) **片內續撈**——呼叫者拿 slice_plan 逐片呼叫 `patent_bulk(source="epo", date_from=片.from, date_to=片.to)`,片內用既有 next_skip 續撈。MCP 面新增參數 `slice_plan=true`(planning-only 呼叫,回切片計畫不拉 records)。守恆自證:各片 total 相加與母數差 > 5% → `error_code=SLICE_INEFFECTIVE` fail-fast(切片在該 query 未生效/假切),不靜默交殘池。無 date 範圍(date_from/date_to 皆缺)且 total > wall → `error_code=DATE_RANGE_REQUIRED`(不自己猜全史範圍,fail-fast 天條)。拒絕方案:server 側單呼叫內逐片全拉(撞 MCP timeout,正是 BR1 根因的重演)。
- DD-9(revise 2026-07-10): **count-probe 硬預算**:遞迴深度 cap 6(年→半年→季→月→半月→週)、probe 總呼叫數 cap 32。觸頂仍有片 total > wall → 該片標 `truncated:true` 誠實回報(呼叫者可再手動細切該片),不無限探。probe 也走 OPS search 吃節流,cap 同時控成本與單呼叫時長。
- DD-10(extend 2026-07-15): **POST 無法繞 GPSS condition-length 牆——實測封死,分片是唯一解**(BR_20260715)。GPSS 長 query 撞兩道獨立的牆:牆A(MCP server httpx **GET** 塞長 URL → HTTP 414)、牆B(TIPO 後端回 `GPSS_ERROR: Exceeded search condition length`,限制檢索條件字串本身長度)。曾疑「改 POST 把 query 放 body 可繞牆A」,2026-07-15 對 `tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api` 做對照探測**證實 POST 死路**:(A)POST 空請求→`usage:...`(38B);(B)POST userCode 只在 **body**→`usage:...`(38B,**與空請求相同**);(C)POST userCode 在 **URL**→`userCode not exist`(96B);(D)GET userCode 在 URL→`userCode not exist`(96B)。**B==A 且 C==D → GPSS 後端只讀 URL query string,POST body 一律忽略**。故牆A 無法用 POST 繞;牆B 本就與傳輸無關。結論:**唯一解是把 query 拆短**——拆短後 URL 短(過牆A)、condition 字串短(過牆B),一石二鳥。拒絕方案:改 POST(body 不讀)、壓縮/編碼(condition 解開一樣長)、拆 header(牆B 是字串長度)。
- DD-11(extend 2026-07-15): **GPSS query-slicing = 工具層全自動拆分,recall-preserving,絕不交呼叫端**(BR_20260715)。`bulk_harvest`(GPSS keyword 分支)偵測 `Exceeded search condition length` 時**自動分片重試**,對呼叫端透明回單一 union 結果。設計要點:(1)**只拆最長的正向 AND-of-OR 群,NOT 群原樣完整保留**——數學硬約束:`(Bx∪By) ∩ C ¬D = (Bx∩C¬D) ∪ (By∩C¬D)`(交集對聯集分配律)成立,但 `¬(D1∪D2) = ¬D1∩¬D2 ≠ ¬D1∪¬D2`,拆 NOT 群會靜默漏排雜訊、precision 漂移。(2)解析 `spec.keyword` 布林式(GPSS 欄內中綴語法 and/或`+`OR/`-`NOT + 引號片語 + 括號)為頂層 AND 群,選詞數最多的**正向** OR 群二分為 `Bx`/`By`,各成子查詢。(3)**遞迴分片**:子查詢仍超長則繼續二分(比照 EPO slice_plan 遞迴二分),深度 cap 對齊 DD-9(6)。(4)**pubno union 去重**:各子查詢 records 以 pubno 為 key 聯集去重,per-page absorb 照舊落 patentdb。(5)**透明回傳**:envelope 補 `sharding:{applied:true, shards:[{query_frag,total,landed}], union_total, union_landed}` 供稽核。(6)**fail-fast 邊界**:連「單一 OR 詞 + 全 AND/NOT」都仍超長 → `CONDITION_LENGTH_IRREDUCIBLE` 要求呼叫端縮詞。**為何全自動不交 agent**(使用者 2026-07-15 拍板):拆法是確定性集合論運算(哪群最長=數詞數、拆幾片=二分到合法、NOT 群零選擇),無一步需智能;交 tool 一次做對、可稽核,不讓 agent 有拆錯 NOT 群靜默漏排的出錯點。輔以 SKILL 紀律(檢索式勿塞冗詞、優先分類軸)治理「該罵 agent 的長」,但大型 landscape 召回式的長是方法論本質,必須工具層承接。與 DD-8/DD-9 的關係:EPO 走 **date-slicing**(skip wall,母數維度);GPSS 走 **query-slicing**(condition length,query 字串維度)——兩者是姊妹功能,分片維度不同。

## Risks / Trade-offs

- 舊工具名散落於 flow 文件/歷史 playbook — mitigation: TOOL_RENAMED stub 給 typed 修正 + SKILL.md §5 同步改名
- `test_classification_bulk_export.py` 若直打 MCP wrapper 會撞 stub — mitigation: 偵查確認其測的層級,必要時改打 `patent_bulk`
- EPO `keyword_field` 參數實際被忽略(恆 `txt=`)— 契約文件如實標注,不假裝支援
- 切片邊界重複計數(date 區間端點重疊)— mitigation: 切點用互斥區間(前片 to = D,後片 from = D+1 日);COALESCE upsert 冪等本就容忍重拉
- probe 期間 total 漂移(新公開案進來)— mitigation: sum_check 容忍 5% 誤差,超過才 SLICE_INEFFECTIVE

## Critical Files

- `src/patent_mcp_server/search_dispatcher.py` — `bulk_export`(:301) / `bulk_harvest`(:450) / `epo_bulk_harvest`(:673) / `_keyword_to_cql`(:484) / `_bulk_pull_epo`(:587);新增 `bulk()` 統一路由
- `src/patent_mcp_server/patents.py` — 三舊 MCP wrapper(:2796/:2871/:2925)、`_TOOL_RENAMED_ENVELOPE`(:2995 起);新增 `patent_bulk`
- `tests/test_tool_renamed_stubs.py` — stub 測試模式範本
- `skills/patentworks/SKILL.md` — §5 line 181(bulk 條目)、line 190(EPO 能力)
