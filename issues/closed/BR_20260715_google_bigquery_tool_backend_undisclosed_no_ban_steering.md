# BR: google_* 專利工具後端＝BigQuery 但工具名不揭露，patentworks 無「禁 BigQuery 路徑」導向

- **Date**: 2026-07-15（自 opencode `BR_20260713_central_dispatcher_no_policy_gate_for_mcp_app_tools` 重歸屬而來）
- **Severity**: high（違反環境級 BigQuery 禁令的呼叫可被 agent 反射送出，僅靠遠端計費上限僥倖擋下）
- **Component**: patentmcp — `google_get_patent` / `google_get_patent_claims` / `google_get_patent_description` 工具後端揭露 + patentworks companion skill 導向
- **Status**: open
- **Reporter**: main agent（telecam 事實查核 session 觸發）；opencode 端已核對架構後判定非 harness 責任

## 一句話

`google_get_patent` 系列工具的後端是 **Google BigQuery Google Patents Public Data**（不是 google.com 網頁），但**工具名完全不揭露這件事**，且 patentworks skill 沒有「專利查核只走 TIPO GPSS / EPO OPS / USPTO PPUBS、禁 `google_*` BigQuery 路徑」的導向。結果 agent 反射選用 `google_get_patent`（6 次 batch）全部打到 BigQuery，僅因**遠端計費上限** `500 bytesBilledLimitExceeded` 才被擋下——攔在 Google 那端，不是我們攔的。

## 觸發實況（證據鏈）

1. 任務：事實查核，需驗證 11 件專利書目。
2. Agent 反射選用 `google_get_patent`（6 次呼叫，batch）。
3. 全部回 `500 bytesBilledLimitExceeded`（`Query exceeded limit for bytes billed: 10737418240. 269599375360 or higher required.`）——這是 **Google BigQuery** 的計費上限訊號，鐵證後端＝BigQuery Google Patents Public Data。
4. 使用者禁令：**禁用 Google BigQuery**（session 內明示，環境級約束）。
5. Agent 改走 `ppubs_batch_get_claims` / `patent_get_claim1`（回 `"source":"tipo"` = TIPO GPSS 官方 API），乾淨、無污染。

打擊半徑：**零資料污染**（6 次 BigQuery 呼叫全 500 失敗）。但這是僥倖——遠端計費上限剛好擋住，若上限夠高 BigQuery 就會被實際命中。

## 根因（patentmcp 域內兩層）

```
第1層  工具名不可分辨後端：`google_get_patent` 看起來像「查 Google 專利網頁」，
        實際打 BigQuery 計費 API。工具的存在性訊號與其計費/禁令屬性完全脫鉤，
        誘導 agent 在 point-of-decision 反射誤選。
第2層  patentworks companion skill 未載明後端分流紀律：沒有「專利查核只走
        TIPO GPSS / EPO OPS / USPTO PPUBS、禁 google_* BigQuery 路徑」的導向；
        且 opencode enablement.json 對 patentmcp 的 companion 宣告為空
        （patentmcp 側應提供正確的 companion 宣告來源）。
```

## 為什麼這不是 opencode harness 的責任（重歸屬依據）

opencode 端核對原始碼後確認：
- 沒有「central dispatcher」在統籌攔截工具呼叫；bash 的 denylist 是 bash tool local 的防呆預篩（作者明寫 "not a security boundary"），不是共用硬閘。
- opencode 真正的中央 policy 是 permission 系統，MCP app 工具在該路徑是 auto-allow。
- 領域知識「`google_get_patent`＝BigQuery＝該環境禁用」屬 patentmcp 域，opencode 不該 hardcode patent 專屬字串。
- 使用者禁令是 session 級明示，本就不可能靠 opencode 編譯期 denylist 解。

（詳見 opencode `issues/BR_20260713_central_dispatcher_no_policy_gate_for_mcp_app_tools.md` 的「更正與重歸屬」段。）

## 修正方向

1. **（主）工具後端揭露**：在 `google_get_patent` / `google_get_patent_claims` / `google_get_patent_description` 三工具的 description 明載「後端＝Google BigQuery Public Data，**計費**，受環境級 BigQuery 禁令約束；一般專利查核請改走 TIPO GPSS / EPO OPS / USPTO PPUBS」。讓存在性訊號與計費/禁令屬性對齊。
2. **（主）patentworks skill 導向**：在 `skills/patentworks/SKILL.md` 明載後端分流紀律——書目/claims/description 查核**優先且預設** TIPO GPSS（`ppubs_*` / `patent_get_claim1`，`source:tipo`）、EPO OPS、USPTO PPUBS；`google_*` BigQuery 路徑列為**受禁/需明示授權**，非反射預設。
3. **（輔）companion 宣告**：提供正確的 patentmcp→patentworks companion 宣告來源，讓 opencode enablement 能在工具存在時一併載入 skill 導向（現為空）。

## 驗收

- 讀 `google_get_patent` 的 description 即可辨識「BigQuery 計費後端 + 受禁」，不必等 500 才知道。
- patentworks skill 載入後，agent 對「驗證專利書目」的反射預設路徑是 TIPO/EPO/PPUBS，不是 `google_*`。

## 關聯

- 來源／重歸屬自：opencode `issues/BR_20260713_central_dispatcher_no_policy_gate_for_mcp_app_tools.md`
- 同族（MCP app 工具治理缺口，opencode 側）：`BR_20260705_mcp_app_tools_not_autoloaded_subagent_silent_kill`、`BR_20260706_invalid_sink_no_did_you_mean_for_mcp_app_tools`
- 本 repo companion skill：`skills/patentworks/SKILL.md`

---

## Resolution（2026-07-18，fixed）

**現況核對，兩條主修法皆落地**：
1. **（主）工具後端揭露**：`src/patent_mcp_server/patents.py:752 / 794 / 834` 三工具
   （`google_get_patent` / `google_get_patent_claims` / `google_get_patent_description`）
   description 開頭已加
   `[BigQuery-BILLED backend — subject to environment-level BigQuery ban]`。存在性訊號
   與計費/禁令屬性已對齊——讀 description 即可辨識，不必等 500。
2. **（主）patentworks skill 導向**：`skills/patentworks/SKILL.md:30` 已加 **R17 後端分流
   紀律**——書目/claims/description 查核預設 TIPO GPSS（`patent_search` /
   `ppubs_batch_get_claims` / `patent_get_claim1`，`source:tipo`）、EPO OPS、USPTO PPUBS；
   `google_*` BigQuery 路徑列為受禁/需明示授權，非反射預設。

驗收（BR §驗收）達成：description 自述後端 + 禁令；skill 載入後反射預設走官方梯。

**輔項（§3 companion 宣告）**：屬 opencode enablement 側的 registry 補全，跨 repo；
patentmcp 域內兩條主修法已足以恢復「不誤選 BigQuery」的契約，本 BR close。
