# BR_20260730 — patentmcp 只服務 `/skills/patentworks.zip`，沒有 bare `GET /skills` 列表端點（遠端 client 無法「發現」該問哪個名字）

| Field | Value |
| --- | --- |
| Title | patentmcp 缺 bare `GET /skills` 列表端點：zip 可下載但不可發現 |
| Component | patentmcp HTTP introspection surface（`src/patent_mcp_server/_http_app.py`） |
| Reporter | ses_05b51c060（fleet R9 稽核，dispatcher 自驗） |
| Date | 2026-07-30 |
| Severity | medium — `patentworks` 的 zip 實測可下載（200/204837B），但遠端 client 必須**事先知道**名字才拿得到；泛用 R9.2 消費端在列表步驟就失敗 |
| Priority | P2 — 本機 opencode host 走 R9.1 本地半仍可取得；衝擊面限遠端 / 非 opencode client |
| Affected versions/tools/paths | patentmcp 0.6.0；`mcp.json:14` `skillPaths:["skills"]`；`src/patent_mcp_server/_http_app.py:669` 只註冊 `/skills/{_SKILL_NAME}.zip` |

```
State:
Fix: unfixed
Effect: n/a
Custody: unclaimed
Blocker: none
Disposition: accepted
Venue: patentmcp
```

## 1.1 症狀（verbatim）

對活著的 patentmcp server 撥號（`unix:///home/pkcs12/projects/patentmcp/.run/patentmcp.sock`）：

```
GET /skills                    -> 404   body: "Not Found"
GET /skills/patentworks.zip    -> 200   204837 bytes        <- 下載端點正常
GET /health                    -> 200                       <- CONTROL：服務活著
```

`GET /skills/patentworks.zip` 回 200 證明**下載那半是好的**；`GET /skills` 回 404 證明**發現那半不存在**。

## 1.2 消費端實測（決定性）

用 opencode 的 R9.2 消費端（`packages/opencode/src/mcp/skill-fetch.ts`）撥號：

```
{"id":"patentmcp","kind":"failed","reason":"GET /skills returned HTTP 404 for app probe-patentmcp"}
```

對照組（同一支消費端、同一次執行，三個成功）：

```
{"id":"docxmcp", "kind":"materialized","skills":["doc-workflow"]}
{"id":"drawmiat","kind":"materialized","skills":["flowchart-author","miatdiagram"]}
{"id":"pmsmcp",  "kind":"materialized","skills":["pmsmcp"]}
```

**這是本 BR 的核心論點**：一個泛用 client 不會憑空知道要問 `patentworks`。它先打 `GET /skills` 拿名單，再逐個下載。列表端點缺席就等於「skill 存在但沒有任何自動化路徑能發現它」——即使 zip 本身好端端地服務著。

## 1.3 Findings

```
Findings:
F1 bare GET /skills 列表端點不存在（僅註冊了 .zip 那條 route） Fix: unfixed Disposition: accepted Venue: patentmcp
F2 route 硬編碼單一 skill 名（_SKILL_NAME），新增 companion 需改 code 而非資料 Fix: unfixed Disposition: deferred Venue: patentmcp
```

## 1.4 RCA

`src/patent_mcp_server/_http_app.py:669`：

```python
Route(f"/skills/{_SKILL_NAME}.zip", skill_zip, methods=["GET"]),
```

`_SKILL_NAME = "patentworks"`（`:32`）。route 表裡**只有這一條** `/skills*`：

```
grep -c 'Route("/skills"' src/patent_mcp_server/_http_app.py  ->  0
```

也就是說 F1 與 F2 是同一行程式碼的兩面：因為名字被 f-string 寫死進 route pattern，既沒有列表可回，也沒有「逐名服務」的通用形狀。

`mcp.json:15` 的 instructions 說「downloadable at `/patentmcp/skills/patentworks.zip`」——這是 gateway 前綴下的路徑，對**直接撥 socket 的 client** 不適用；而規範 R9.2 釘死的是 server root 的 `/skills/<name>.zip`。實測 socket 上 `/skills/patentworks.zip` 確實可用，所以下載那半合格，缺的純粹是列表。

## 1.5 Mandatory History Review

| Aspect | Finding |
| --- | --- |
| Same-family BRs | `none matching this defect` — 掃 `issues/` + `closed/` + `observing/`，pattern：`skillPaths`/`/skills`/`skill.?ship`/`companion`/`SKILL_NOT_SHIPPED`/`HALF_SHIPPED`/`R9`/`zip`。命中皆為**旁系**：`BR_20260715_google_bigquery_tool_backend_undisclosed…`（companion 後端分流 + enablement companion 宣告為空）、`BR_20260712_orchestrator_skipped_patentworks_probe…`（領域盤查反射）、`BR_20260706_patentworks_projection_stale…`（skill 投影漂移，本機 pool）、`BR_20260628_workflow_source_ladder…` / `BR_20260628_tools_not_surfaced…`（companion 內容缺工具）。皆非「缺 bare list 端點」。最近親 `closed/issue_20260721_r17_minimum_operational_toolset_conformance.md`。 |
| Recurrence | `no` — 「只有 `.zip` 而無 bare `GET /skills`」此症狀先前未被 BR 修過。 |
| Event log / KB hits | `none — event_search q="skill shipping companion remote" → []；wiki_search q="skillPaths companion skill R9" → []`（`.specbase/` 存在、runner 正常）。 |
| Owning spec / contract | `specs/patentmcp/mcp-standard-conformance/`（本 repo 自有 conformance spec，**直接觸及**）：`spec.md:9` 明列「naming (R4), and **skillPaths (R9)** are already」、`spec.md:57` 斷言「`/skills/{name}.zip`, the landing page `/`, and `webctl.sh` verbs all still work」——**只釘死 zip payload 端點，完全未涵蓋 bare list 端點**，這正是本缺陷得以存活的規範缺口。另 `specs/patentmcp_r17-minimum-operational-toolset/`（R17.5 parity，`closed/issue_20260721_…:34` 自評 ✅ 但同樣未實測 list 端點）。修復應連帶補這條條文，否則下一次自檢仍會回綠。 |
| Isomorphic failures | `partial` — 同 repo 內未見其他「宣告了但沒接上」的同形失敗（`.zip` 端點本身實測可用）。與 bodesign（服務錯格式）、specbase（零 route）同屬「R9 遠端半只做一半」家族，機制各異。 |

## 2. 修復方向（venue: patentmcp）

規範要求（`mcp-integration-standard` R9.2 / R9.4.1 / R9.8）：

1. 新增 `GET /skills` 回 companion 清單。payload 形狀由 R9.8 容忍多種（`{"skills":[{"name":…}]}` / `{"skills":["…"]}` / `["…"]` / `{"skills":{…}}`），但**元素必須是 bare skill name**，不可是檔名（見 bodesign 的反例 BR）。
2. 把 `/skills/{name}.zip` 改成參數化 route（`{name}` path param），並對未知名回 typed 404、對 traversal 回 404/403。
3. 順帶滿足 R9.7.1 producer 端：zip 內不得有絕對路徑、`..` 片段、symlink。
4. 更新 `specs/patentmcp/mcp-standard-conformance/spec.md`，把「bare list 端點」寫進條文——否則自檢仍會漏。

可參考同 fleet 已合格的 Python 實作：`docxmcp/bin/_skill_shipping.py` + `docxmcp/bin/mcp_server.py:7123-7124`。

## 3. 驗證計畫

- 正向：`GET /skills` 回 200 且含 bare 名 `patentworks`；`GET /skills/patentworks.zip` 仍回 200 且 bytes > 0（回歸）
- 負向：未知名 → typed 404（非 500、非 200 空 archive）；`..%2Fbin` → 404/403
- 端到端：`McpSkillFetch.materialize` 對本服務回 `kind:"materialized"` 且 `skills` 含 `patentworks`
- 機檢：`McpConformanceProbe.run()`（opencode `76d58bb64`）對 patentmcp 的 `MCPSTD_SKILL_HALF_SHIPPED` 消失
