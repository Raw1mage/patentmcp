# BR_20260718 — patent_bulk 的 number-query 入口不顯化 + `@PN` 尾綴靜默 zero_hits

## 軸別
軸A(讓工具能用 / make tool USABLE):number-query 是 GPSS 一等能力,但在 `patent_bulk`
的入口藏在 `keyword + keyword_field="PN"` 組合底下,且對常見的錯誤語法**靜默回 zero_hits
不報錯**,導致「API 不能做 number query」的錯誤結論。

## 症狀(實測 live-verified 2026-07-18)
場景:手上有一份公開號清單(CN 池 ~12,172),要一發用 API 額度批量補書目(申請號+三日期)。

1. 直覺寫法 `patent_bulk(source="gpss", keyword="(CN117338286 or CN117338290 or ...)@PN",
   keyword_field="PN")` → **`success:true, records:[], total:0, provenance.reason=zero_hits`**。
   - 整包用括號 + 尾綴 `@PN`(GPSS web 進階檢索的合法號碼軸語法)被 keyword 引擎當普通全文字串,
     命中零。**但工具回 success:true、zero_hits,不報「語法不被支援」**——看起來就像「API 不支援
     number query」。

2. 正確寫法 `patent_bulk(source="gpss", keyword="CN117338286 or CN117338290 or CN117357099",
   keyword_field="PN")`(**不加 `@PN` 尾綴、不加外括號**) → 完美命中 4 筆全書目
   (appno + app_date + pub_date + prio_date + 中文 title/abstract + claim1 + cpc/ipc),
   `patentdb_absorb` 自動落庫。number query 完全可用。

兩者差別僅在 `@PN` 尾綴 + 外括號。合法的 web-進階-檢索號碼軸語法在 `patent_bulk` keyword 軸
會靜默失敗。

## 根因
- `patent_bulk` 沒有一等的號碼清單軸參數(如 `pub_number: List[str]`);number query 只能經由
  `keyword=... + keyword_field="PN"` 隱式達成。這條路徑在 docstring 沒有明講「怎麼餵一份公開號
  清單」,呼叫者得自己猜。
- 對 GPSS 號碼軸的 `@PN` 尾綴 / 外括號語法**沒有偵測 + 拒絕/清洗**:直接當全文送 → zero_hits,
  且回 `success:true` 而非 typed 錯誤,違反 fail-loud。

## 建議修法(擇一或並行)
1. **顯化入口**:給 `patent_bulk` + `patent_search` 加一等 `pub_number: List[str]` 參數,
   內部組成 `no or no or ...` + field=PN,呼叫者不必知道 keyword 軸的隱式用法。docstring 明列
   「number-list 匯出」範例。
2. **fail-loud**:偵測 keyword 內含 `@PN` / `@AN` 尾綴或整包外括號的號碼軸語法 → 要嘛自動清洗
   (strip 尾綴 + 拆 or),要嘛回 typed `NUMBER_AXIS_SYNTAX_UNSUPPORTED` 明示「keyword 軸不吃
   `@PN` 尾綴,請用 pub_number 參數或純 `no or no`」——絕不靜默 zero_hits。
3. **zero_hits 分級**:number/PN 軸 zero_hits 時,若 keyword 疑似號碼語法,provenance.reason
   標 `likely_number_syntax_error` 而非籠統 `zero_hits`,給呼叫者自救線索。

## 影響
- 阻塞了「用 API 額度一發批量補書目」的最短路徑,誤導成「只能逐批爬 web session」的繞路。
- 任何持一份公開號清單想批量匯出的使用者都會踩(這是專利檢索最常見的批量作業之一)。

## 現況繞過(不卡主線)
已用正確語法 `keyword="no or no or ..." + keyword_field="PN"`(不加 `@PN` 尾綴)推進 enrich,
API 額度路徑可用。本 BR 記工具磨擦供後續顯化入口 + fail-loud。

## Resolution (2026-07-18, CLOSED)

plan `patentmcp_patent-bulk-number-axis-fail-loud` 三修法並行落地(建議修法 1+2+3 全採):

1. **顯化入口(DD-1)**:`patent_bulk` 新增一等 `pub_number` 參數;`patent_bulk`+`patent_search`
   的 `pub_number` 型別放寬 `Optional[Union[str, List[str]]]`——單值維持原行為(向後相容),
   清單內部 join 成 GPSS `no or no or ...` PN 形式。docstring 明列 number-list 匯出範例並警示
   勿在 keyword 手刻 `@PN`/外括號語法。呼叫者不必再知道 keyword 軸隱式用法。
2. **fail-loud(DD-2/DD-4)**:`normalize_query`(單一收斂點)偵測 keyword 內 `@PN`/`@AN`/`@PD`
   尾綴 + 整包外括號的 web-進階-檢索號碼軸語法 → **預設清洗**(strip 尾綴 + 拆外括號,記
   provenance `number_axis_cleaned` 透明告知);清洗後仍非合法號碼列 → typed
   `NUMBER_AXIS_SYNTAX_UNSUPPORTED`,**絕不靜默 zero_hits**。偵測條件收窄,一般全文 keyword 不誤傷。
3. **zero_hits 分級(DD-3)**:`_run_gpss` zero_hits 時,PN 軸/已清洗/疑似號碼語法 → provenance
   note `likely_number_syntax_error` + 自救 hint,而非籠統 `zero_hits`。

**根因確認**:`patent_bulk` 原本無 `pub_number` 參數,number query 只能靠 `keyword+keyword_field=PN`
隱式達成;GPSS keyword 引擎不吃 web 進階檢索的 `@PN` 尾綴/外括號 → 當全文送 → 命中零 → 回
success:true zero_hits。同族 `BR_20260709`(closed)已確立「GPSS 不認的欄位/語法會靜默 miss」
教訓,本 BR 為 number 軸的同構修復。

**驗證**:`tests/test_number_axis_failloud.py` 10 綠(清單組成 PN / 單值向後相容 / @PN 清洗 /
清洗後非法 typed 錯 / zero_hits 分級 / 全文不誤判);`tests/` 全套 219 passed 無回歸。

**Changes**:`src/patent_mcp_server/search_dispatcher.py`(QuerySpec.pub_number 型別、
`_clean_number_axis`/`_looks_like_number_axis`/`NumberAxisSyntaxError`、normalize_query 偵測清洗、
_run_gpss PN 清單 join + zero_hits 分級)、`src/patent_mcp_server/patents.py`(patent_search /
patent_bulk `pub_number` 參數 + docstring)。Architecture sync:`specs/architecture.md` line 60。
