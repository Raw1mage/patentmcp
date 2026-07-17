# BR_20260718 — GPSS REST `patent_bulk` 間歇 `Expected JSON but parse failed`(keep-alive fix 不完整),被下游誤判成「GPSS API 無英文召回能力」

- **狀態**: CLOSED(2026-07-18 修復)
- **元件**: `gpss/client.py`(`GPSSClient.search` / `_parse_gpss_json`)→ `patent_bulk(source="gpss")`
- **嚴重度**: 高(靜默失敗 + 誘發下游對「引擎能力」的錯誤定性,污染檢索策略決策)
- **回報者**: 異常偵測前案檢索案(orchestrator)
- **嚴重度升級(2026-07-18 追測)**: 原評「高」→**極高**——下方 TW 中文同式一發也 parse failed,坐實 bug **與語言/國別無關,整條 `patent_bulk(source=gpss)` 撈池主路全面失效**(非 US 英文邊角問題)。

## 症狀(可復現)

常駐 MCP-server 行程內,`patent_bulk(source="gpss")` 對 US 英文 keyword 檢索式間歇性回:

```json
{ "success": false, "records": [], "error_code": "GPSS_ERROR",
  "message": "Expected JSON but parse failed" }
```

**實測請求(2026-07-18,常駐行程)**:
```
patent_bulk(source="gpss",
  keyword='(radar or "millimeter wave" or doppler or "wireless sensing" or "non-contact" or contactless) and ("fall detection" or "vital sign" or respiration or "heart rate" or "sleep monitoring" or breathing)',
  keyword_field="TI,AB", databases=["USA","USB"],
  date_from="2023-01-01", date_to="2023-12-31", num=20)
→ Expected JSON but parse failed
```

**實測請求 B(2026-07-18,TW 中文,常駐行程——與語言無關的硬證)**:
```
patent_bulk(source="gpss",
  keyword='(雷達 or 毫米波 or 微多普勒 or 非接觸 or 無線感測) and (跌倒 or 生命徵象 or 呼吸 or 心率 or 睡眠監測)',
  keyword_field="TI,AB", databases=["TWA","TWB"],
  date_from="2023-01-01", date_to="2023-12-31", num=20)
→ Expected JSON but parse failed
```

> **兩發對照的意義**:英文(US)、中文(TW)、不同庫(USA/USB vs TWA/TWB)、不同詞表,**全部 parse failed**。這從經驗上排除了「某語言/某庫特有」的可能,指向連線層(Cloudflare 截斷 body)而非 query 內容層——與下方根因一致。**`patent_bulk(source=gpss)` 作為「一發帶齊八欄書目(PN/ID/TI/IN/PA/AB/CS/CL)」的唯一撈池主路,現在全面不可用;web `gpss4_advanced_search` 只吐 6 欄(無 applicants/claim),非完整替代。**

## 根因(讀源碼坐實,非臆測)

1. **`client.py:167-179` 註解自證真因**:GPSS 躲在 Cloudflare 後面;長命 MCP-server 行程的單一 `httpx.AsyncClient` 連線池握著 keep-alive 連線,**Cloudflare 閒置一段時間後靜默掐斷**;重用這種半死連線去打深分頁 → 回**截斷/畸形 body** → `resp.json()` / `_parse_gpss_json` parse failed。**只有常駐行程重現(短命 client / curl 永不重現)**。

2. **既有 fix 不完整**:`client.py:176-179` 已 `limits=httpx.Limits(max_keepalive_connections=0)` 試圖每次開新連線繞掉半死重用。**但實測仍炸**(上方 2026-07-18 請求)→ **disable keep-alive 不是唯一觸發路徑**,截斷 body 仍會發生(可能:Cloudflare 對長式 GET/特定 UA/連線頻率的其他掐斷條件、或 response streaming 未完整讀取)。

3. **`_parse_gpss_json`(client.py:42-63)三層 sanitize 救不回**:strict → strict=False(容忍 raw control char)→ illegal-escape 修復。這三層針對的是**格式畸形**(GPSS 未跳脫的反斜線、control char);但本 bug 的 body 是**被截斷**(內容不完整),非格式問題,故三層都 return None → `Expected JSON but parse failed`。

## 打擊半徑 / 下游污染(這是嚴重度高的真因)

此 `parse failed` 被本案 **DD-53** 誤讀成「**GPSS API 對英文 keyword 全 zero_hits、沒有英文召回能力**」,據此拍板「英文檢索整個改宗 EPO / 走 web 路徑」。

**這是把連線層 bug 誤判成引擎能力缺陷**:
- `parse failed`(端點回非合法/截斷 JSON,連線層)≠ `zero_hits`(引擎查了真沒有,能力層)。兩者語義完全不同,不可互換。
- GPSS REST API 有沒有英文召回能力,此 bug 完全無法證明——它在 JSON 解析前就掛了,引擎根本沒機會回結果。
- 「堂堂 API 不可能沒有英文查詢能力」——正確;現象是連線 bug,不是語言能力缺陷。

## 建議修法(供 patentmcp owner 評估,不代修)

1. **截斷偵測 + 重試**:`resp.text` 拿到後,若 `_parse_gpss_json` 回 None,先判斷是否**截斷**(body 結尾不是合法 JSON 閉合 / `Content-Length` 對不上 / body 明顯短於 `total-rec` 應有量),截斷則**換新連線重試 N 次**(而非直接 return parse failed)。
2. **短命 client fallback**:偵測到常駐行程的截斷,對該發改用**一次性短命 `httpx.Client`**(註解自承「短命 client / curl 永不重現」)重打同一 URL。
3. **response 完整讀取**:確認 `resp.text` 是在 response 完整落地後才取(非 streaming 中途),排除讀取時序造成的截斷。
4. **錯誤語義分流**:`parse failed` 的 error 明確標記為 `transport/truncation`,**禁止下游把它當 `zero_hits` / 「無召回能力」**——error message 應攜帶 `raw[:500]` 佐證是截斷而非空結果(現已有 `raw` 欄,但下游 DD-53 仍誤讀,建議 error_code 細分如 `GPSS_TRUNCATED_BODY`)。

## 對本案(異常偵測前案檢索)的影響

- **DD-53「英文改宗 EPO」的地基前提(API 英文 zero_hits)須重評**——真因是本 bug,非引擎能力。
- US 池應回歸 **DD-56 定案:`patent_bulk` API 主撈**(一發回完整書目含 abstract,免事後 enrich),web `gpss4_advanced_search` 僅額度耗盡 fallback。此 bug 修好前,US 主撈受阻。
- 本案已 DD-79 誠實補記此根因;不在 patentmcp 側代修,待 owner 修復後回歸 API 主撈。

## Resolution(2026-07-18)

恢復的契約:**transport 失敗與能力層 zero_hits 必須在 error_code 層分流,不得互換**(建議修法 1/2/4 全部落地)。

- `gpss/client.py`:`_parse_gpss_json` 回 None 時先用**一次性短命 client**(`GPSSClient._fresh_get`,短命連線實測從不復現截斷)重打同 URL `_TRUNCATION_RETRIES=2` 次;仍失敗 → typed `{error_code:"GPSS_TRUNCATED_BODY", transport:"truncation", raw[:500]}`,error 文案明示「TRANSPORT failure, NOT an empty result」。
- 順手移除 client.py 重複 `import json`。
- 驗證:`tests/test_br20260718_fixes.py`(fresh-retry 救回截斷體/重試耗盡回 typed error/乾淨體不觸發重試)+ 既有 `test_gpss_rotation.py`/`test_patent_bulk.py`/`test_search_dispatcher.py` 全綠。
- 下游影響:`search_dispatcher.py` 既有 transient retry 路徑不受影響(判斷用 `success`/`status`,非 error 字串);DD-53「英文改宗 EPO」地基前提確認須重評(歸檔於本案側)。
