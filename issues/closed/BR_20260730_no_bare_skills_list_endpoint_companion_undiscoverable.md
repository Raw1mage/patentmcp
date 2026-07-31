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
Fix: fixed (initial 5167774, review-driven follow-up 03a2420 — see §5;
     VANS-driven follow-up eb385d0 / 9280614 / 3dc8272 — see §6)
Effect: live — 全部 commit 皆已載入執行中的行程（SPLIT 狀態已於 2026-07-31 解除）。
  判別式（非 sha256 比對——見 §6 C7）：
    proc started 2026-07-31T00:06:30Z  >  source mtime 2026-07-30T16:53:22Z
  亦即行程晚於原始碼，import 時綁定的就是這批位元。
  上一版此處記為 SPLIT，因當時 proc 起於 13:13:02Z、早於 mtime 3h40m，
  而容器無 --reload / watcher，CPython 在 import 時綁定 module，
  bind mount 換檔不重載——sha256 相同仍是舊碼。
  2026-07-31 `./webctl.sh restart` 後複驗：/health 200、/skills 200（bare name,
  file_count 30）、/skills/patentworks.zip 200 130270B、unknown → typed
  SKILL_NOT_FOUND、非 ASCII 單段 → typed SKILL_NAME_INVALID（無路徑洩漏）、
  `..%2F` → router plaintext 404（兩層分明）。
Custody: patentmcp coordinator (owns fix + verification + merge, a2a-d2d §3.1.1)
Blocker: none
Disposition: accepted
Venue: patentmcp
```

**Closed: 2026-07-30** by patentmcp coordinator (`ses_04db723af`) — the DEFECT this
BR was filed for (bare `GET /skills` absent) is verified AND effective.

**Deployment completed 2026-07-31.** At close time the VANS-driven follow-up delta
(§6) was committed-not-deployed, so the Effect block was recorded as SPLIT rather
than claiming a closed loop. The user authorised the restart on 2026-07-31;
`./webctl.sh restart` ran clean (exit 0) and the delta is now loaded — Effect is
plain `live`, with the proc-start-vs-mtime discriminator recorded above. No scoped
remainder (the docxmcp same-shape defect is a SEPARATE BR in that repo, `6c25a0d`).

**Re-opened then re-closed 2026-07-30.** The first close was PREMATURE: an
adversarial review (gpt-5.6-terra, §5) found five defects the original fix had
introduced or left, two of which were real contract violations. The BR was pulled
back out of `closed/`, the defects fixed, and re-verified. See §5.

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
F1 bare GET /skills 列表端點不存在（僅註冊了 .zip 那條 route） Fix: fixed Disposition: accepted Venue: patentmcp
F2 route 硬編碼單一 skill 名（_SKILL_NAME），新增 companion 需改 code 而非資料 Fix: fixed Disposition: accepted Venue: patentmcp
```

F2 被一併修掉而非 deferred：reporter 判斷正確——F1/F2 是同一行 code 的兩面，
只補一條 list route 而讓名字繼續寫死，等於留著同一個根因換個位置復發。

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


---

## 4. 修復紀錄（2026-07-30，patentmcp coordinator）

### 4.1 取捨裁決：修，不標 NOT-A-BUG

reporter 明確把「只有一個 skill、硬編碼夠用、加 list 端點算不算過度工程」交回本 repo 裁決。
裁決為**修**，理由不是「規範說要」，而是：

1. **R9 的受益者是消費端，不是本服務。** 合規 client 不該為每個服務硬編碼 skill 名。
   patentmcp 只有一個 skill 這件事，是**本服務的**內部事實，不是**消費端**能預先知道的事實。
2. **修法確實很小，且 F2 讓它更小。** `_zip_skill()` 早已是通用函式，唯一的硬編碼在 route
   pattern 的 f-string。把名字從「常數」還原成「資料」之後，list 端點幾乎是免費的。
3. **不修的成本會複利。** 留著等於下一個稽核者再測一次、再 file 一次 BR。

### 4.2 改動

| 檔案 | 改動 |
| --- | --- |
| `src/patent_mcp_server/_skill_shipping.py` | **新增**。R9 remote 半的單一實作：`list_shippable_skills()` / `resolve_skill_dir()` / `pack_skill_zip()`。雙重 traversal guard（safe-name regex + resolve 後的 containment check）。無 Starlette 相依，可純單元測。 |
| `src/patent_mcp_server/_http_app.py` | 新增 `skills_list` handler + `Route("/skills")`；`skill_zip` 改吃 `{name}` path param；landing page 改資料驅動（每個 skill 一顆按鈕）；移除已被取代的 `_zip_skill()` / `_skills_root()` / `_SKILL_NAME` 與隨之失效的 `io`/`zipfile`/`Path` import。 |
| `tests/test_br20260730_skill_shipping.py` | **新增** 21 個測試：list 回 bare name（非檔名）、generic 非硬編碼、空樹誠實回 []、8 種 traversal 變體、typed 404、archive hygiene、byte-stability、以及 route 層的 list→download 端到端。 |
| `specs/patentmcp/mcp-standard-conformance/spec.md` | 新增 `Requirement: R4`，並改寫 Purpose——原文把 R9 列為「已合規、out of scope」正是本缺陷存活的規範缺口。 |
| `mcp.json` / `README.md` | instructions 與端點清單改述兩個端點。 |

### 4.3 為什麼靜態自檢會回綠（規範缺口，非實作疏漏）

reporter 指出 opencode 側靜態 conformance 閘對 patentmcp 回綠、第一版撥號探測也漏報。
同一個盲點也存在於**本 repo 自己的** spec：`spec.md` 舊 Acceptance Check 4 只斷言
`/skills/{name}.zip` 「still works」——一個只驗「有 zip 能下載」的檢查，對本缺陷**必然**回綠。

因此本次不只補 code，更補了條文（R4 + Acceptance Check 6），並在 check 6 明寫：
「只斷言 some zip downloads 不滿足本條——那正是本 BR 得以存活的形狀。」

### 4.4 驗證（unit + live，兩層）

單元 / 路由層（`.venv/bin/pytest`）:
```
tests/test_br20260730_skill_shipping.py    21 passed
tests/ (全套回歸)                          382 passed, 15 subtests passed
```

Live probe——對**重啟後真的在跑的容器**打 TCP :8000（本 harness 禁止 curl 直打 UDS）:
```
GET /skills                  -> 200  {"ok":true,"skills":[{"name":"patentworks","file_count":30}],"count":1}
GET /skills/patentworks.zip  -> 200  130270 bytes  application/zip
GET /skills/no-such-skill.zip-> 404  {"code":"SKILL_NOT_FOUND",...}
GET /skills/..%2F..%2Fetc%2Fpasswd.zip -> 404       (另二種 traversal 變體同)
GET /health                  -> 200                 (CONTROL)
```
列表回的是 **bare name**（`patentworks`），非檔名——bodesign 反例的形狀已避開。
`file_count: 30` 與 zip 成員數一致。

zip 由 204837 → 130270 bytes 是**預期**的：新 packer 依 R9.7.1 排除
`__pycache__` / `.pyc`（interpreter-specific，且 `co_filename` 會洩漏絕對建置路徑）。
內容檔案未減少。

### 4.5 附帶發現（不在本 BR scope，未動）

`webctl.sh restart` 因 compose project label 漂移而失敗：跑著的 container 帶
`com.docker.compose.project=patentmcp`（掛 volume `patentmcp_patentmcp-sessions`），
而 `webctl.sh` 用的是 `patentmcp-${USER}` = `patentmcp-pkcs12`（對應另一個空 volume）。
`up --force-recreate` 因此撞名衝突。

本次改用 `docker restart <cid>` 就地重啟——`./src` 是 live bind mount，process 重讀即生效，
不需重建、不動 volume、不冒 token store 搬家風險。此漂移**早於本次改動**（container 建於
07-22），與本 BR 無因果關係，故不在此順手修（避免 scope drift 與 volume 誤動）。
已另記，待獨立處理。

---

## 5. 對抗式覆核與後續修復（2026-07-30，同日稍晚）

### 5.1 為什麼會有這一節：第一次結案下得太早

§4 宣告修復完成並歸檔進 `issues/closed/`。使用者要求**用另一個模型獨立驗證**，遂以
`codex/gpt-5.6-terra`（session `ses_04d1c8d51`）做**對抗式**覆核——指令明寫「目標不是
確認它對，而是找出它錯在哪」，並禁止該 session commit / 重啟 / 改 code（修復決定權留在
本 repo coordinator）。

覆核回報 5 則 findings，**其中兩則是真契約違反**。§4 的「已自行驗收結案」因此不成立，
BR 從 `closed/` 取回頂層重開。

**這件事本身是教訓**：§4 的驗證（21 tests + live probe 全綠）只證明了「我設想的情境會過」，
沒有證明「我沒設想到的情境不會爆」。綠燈不等於正確——這與本 BR 一開始的根因
（靜態閘對缺陷回綠）是**同一個形狀**，只是換了一層。

### 5.2 Findings（覆核回報 → 本 repo 逐項自驗）

依 receipt discipline，**不採信自報**，五項全部自行重跑復現：

| # | 嚴重度 | 內容 | 自驗結果 |
| --- | --- | --- | --- |
| F1 | MEDIUM | `list` 用裸 `is_dir()`（跟隨 symlink、不套 name 規則），`resolve_skill_dir` 卻會拒——**列出來卻下載不到** | ✅ 復現：`linkout`(symlink) / `中文技能`(non-ASCII) 皆 listed 但 resolve 回 `SKILL_NAME_INVALID` |
| F2 | LOW | list 與 pack 各自重掃，無 snapshot；list 後檔案消失 → pack 回 **200 + 22-byte 空 zip** 而非 typed failure | ✅ 復現：`race` list 宣告 `file_count=1`，刪檔後 pack 得 22 bytes / 0 members |
| F3 | LOW | route 層的 traversal 測試沒測到 guard——`%2F` 被 Starlette **router** 先擋（plaintext 404），根本沒進 handler | ✅ 復現（**且與本 repo 自查獨立同識**，見 5.3） |
| F4 | LOW | 測試斷言 `assert n.startswith("patentworks/")` 落在 `for` 迴圈**外**，只驗最後一個成員 | ✅ 復現：`names=["/unsafe","patentworks/SKILL.md"]` 會通過 |
| F5 | LOW | 404 body 直接回 `e.message`，洩漏容器絕對路徑 `looked in /app/skills` | ✅ 復現 |

`foo.zip` 子論點另驗：名為 `foo.zip` 的目錄功能上**可**下載（`/skills/foo.zip.zip` → 200），
但違反本 repo 自己的 bare-name 斷言 `not n.endswith(".zip")`。歸入 F1 同一根因（list 未套
name 規則）一併解決。

### 5.3 交叉驗證：F3 由兩邊獨立發現

在等待覆核期間，本 repo coordinator 自行複查 §4.4 的 traversal 證據時，**獨立撞到同一點**：
先前三個 probe 用 `-o /dev/null` 只收狀態碼，無法分辨 404 來自哪一層。改看 response body：

```
..%2F..%2Fetc%2Fpasswd  ->  body="Not Found"                 ROUTER（guard 從未執行）
%2e%2e%2fbin            ->  body="Not Found"                 ROUTER
a%2Fb                   ->  body="Not Found"                 ROUTER
..  /  .  /  %00        ->  body={"code":"SKILL_NAME_INVALID"} MY GUARD
```

Starlette **先 decode 再 match**，`%2F` 還原成真斜線後，單段 `{name}` 匹配不到 → 在進
handler 前就 404。**安全結果無誤**（三層縱深都在，guard 本身在 unit test 有直接測到 8 種
變體），但 §4.4 拿那三個 probe 當「雙重 guard 已驗證」的證據**是空的**，措辭必須更正。

兩個獨立來源得到同一結論，此點定案。

### 5.4 修復

`src/patent_mcp_server/_skill_shipping.py`：

- **F1（結構性修復，不只補洞）**：`resolve_skill_dir` 升為**唯一准入閘**，`list_shippable_skills`
  與 `pack_skill_zip` 都走它。「listed ⇒ downloadable」因此是**結構保證**，而非兩套規則
  湊巧一致。新增第 2 道 guard：entry 本身不得是 symlink，且**在未 `.resolve()` 的路徑上檢查**
  ——因為 `.resolve()` 會抹掉正在測試的那個事實，單靠 containment check 會放行指向 root
  **內部**的 symlink。
- **F1 副作用（反靜默）**：被擋下的目錄不再靜默消失，改發 `_log.warning`——「看起來像 skill
  卻無法服務」是作者的錯誤，operator 必須看得到。wire payload 仍不含它（消費端契約是
  「我列的你都拿得到」）。
- **F2**：`pack_skill_zip` 空成員 → 拋 typed `SKILL_EMPTY`（新 error code）。22-byte
  end-of-central-directory **是合法 zip**，配 200 回去等於「成功但什麼都沒有」——正是本 BR
  要殺的靜默失敗形狀。
- **F5**：所有錯誤訊息移除檔案系統路徑；完整細節（含 root）改走 server log。

`tests/test_br20260730_skill_shipping.py`（21 → 28）：

- **F4**：斷言移進 loop。
- 新增 7 個覆核驅動的回歸測試，含 **F3 的兩面**：一個釘住 `%2F` 必須止於 router
  （斷言 body **不含** `SKILL_`），一個確保 route 層真的能觸達 guard（用單段但違規的
  `中文.zip`，斷言 body **是** typed `SKILL_NAME_INVALID`）。沒有後者，guard 在 HTTP 層
  就是零覆蓋。

### 5.5 重驗

```
tests/test_br20260730_skill_shipping.py   28 passed（原 21 + 7 覆核回歸）
tests/（全套）                            389 passed + 15 subtests，零回歸
```

Live probe（容器重啟後，TCP :8000）：

```
GET /skills                    -> 200 {"ok":true,"skills":[{"name":"patentworks","file_count":30}],"count":1}
GET /skills/patentworks.zip    -> 200 / 130270 bytes                      （回歸未破）
GET /skills/nosuch.zip         -> 404 {"detail":"no such shippable skill"} （F5：路徑不再洩漏）
GET /skills/..%2F..%2Fetc%2Fpasswd.zip -> 404 body="Not Found"            （F3：止於 router）
GET /skills/%E4%B8%AD%E6%96%87.zip     -> 404 code=SKILL_NAME_INVALID     （F3：guard 確實觸達）
```

隔離樹實測（F1/F2 修復生效）：

```
skills/{linkout->outside, 中文技能, dotonly(僅.hidden), emptydir, race, good}
  list -> ['good','race']        每個 listed name 都 resolve OK
  LOG  -> not advertising 'linkout' … SKILL_NAME_INVALID (symlink)
          not advertising '中文技能' … SKILL_NAME_INVALID (safe-name)
          not advertising 'dotonly'/'emptydir' … SKILL_EMPTY
  race 刪檔後 pack -> SKILL_EMPTY（不再是 200 空 zip）
```

### 5.6 待辦（不在本 BR，另案）

**docxmcp 同源同病**：參考實作 `/home/pkcs12/projects/docxmcp/bin/_skill_shipping.py` 實測
也會 list 出 non-ASCII 名稱卻在 resolve 時拒絕（它有擋 symlink，但同樣沒對 list 套 name
規則）。依 BRNS 應在 docxmcp repo 立案，不在此順手修。

---

## 6. VANS 獨立驗證（2026-07-30，三輪）

§5 的覆核用的是舊 BRNS 格式。之後 fleet 立了正式的 VANS 契約
（`validation-adversary` skill），使用者要求依新契約再驗一次——**修完 BR 跑一次
VANS 是正常下一步**，不是補救。

派發：`ses_04c459f11`（`codex/gpt-5.6-terra`，異 provider、獨立 session、唯讀）。
工作單只給 SSOT 路徑與 8 條待驗宣稱（C1–C8），**不給我的結論、不給已知疑點**
——否則是確認而非獨立驗證。

### 6.1 三輪結果

| 輪 | 裁決 | 主要內容 |
|---|---|---|
| R1 | pass=5 fail=2 unverified=1 | C5/C8 兩條契約**只有實作錨點、沒有測試錨點** |
| R2 | pass=7 fail=1 unverified=0 | 兩個 finding 已修；新發現 C7 部署未生效 |
| R3 | **pass=8 fail=0 unverified=0** | CLEARED |

### 6.2 R1 的兩個 finding（我逐一自行重現後確認屬實，均不駁回）

依 VANS §5，finding 是**宣稱不是判決**。我用自建隔離樹（非它的 fixture）重跑
mutation，且**先證明 harness 真的載到隔離副本**才採信結果：

```
MUT8 刪除兩處 _log.warning          -> 28 passed   （全 suite 無 caplog，零觀測）
MUT6 containment check -> if False   -> 28 passed
MUT7 移除 in-archive symlink 排除    -> 28 passed
MUT5 移除 .pyc suffix 排除           -> 28 passed（種一個散落 .pyc 後才變紅）
```

MUT5 的診斷特別精確：真實樹的 11 個 `.pyc` **全在** `__pycache__/` 底下，先被
`_EXCLUDED_DIRS` 攔掉，所以 suffix 規則從未觸發。那條斷言是**碰巧**有效的。

### 6.3 修復（eb385d0 / 9280614 / 3dc8272）

補 5 個測試錨點，並以 **9 個 mutation 反證每個都能變紅、且各只紅一個**——
綠測試不等於有效測試，這正是本 BR 的根因形狀。

其中 containment check 值得記：guard 2 還站著時，guard 3 從公開 API **走不到**
（POSIX 上非 symlink 的 child 不可能 resolve 出父目錄），天真 fixture 永遠測不到。
改測它真正防的 TOCTOU——`resolve_skill_dir` 讀 `skills_root()` 兩次，兩次之間
root 被換掉（部署切 symlink）時 candidate 會落在 root 已不再包含的樹裡。

它 flag 的三個 gap 全部處理，不只挑好做的：
- **self-heal 繞過 guard** → 抽 `scripts/_compose_lib.sh` 為單一來源。刻意**不複製**
  一份 guard：兩個 caller 各持一套規則自由漂移，與 list/download 分歧是同一個
  缺陷形狀，而那正是這張 BR 剛在 Python 側修掉的東西。
- **不可讀 root 靜默回 `[]`** → `root.exists()` 但非目錄時出聲；完全不存在仍靜默
  （合法的「無 companion」）。測試雙向都釘。
- **guard 無自動化測試**（它 flag 兩輪、我兩輪未認領）→ `tests/test_compose_drift_guard.py`，
  以 PATH 上的 docker stub 驅動真 lib，釘住三分支決策與拒絕的可診斷性。

### 6.4 我自己找出、且推翻自己先前宣稱的兩件事

**「全套 389 passed 零回歸」是帶著 env var 跑的。** 裸跑 `pytest tests` 在 pristine
HEAD 就是 7 failed——`patents.py:79` 在 import 時凍結 `_DOCTRINE_PATH`，五個測試檔
各自 `setdefault`、另四個匯入卻沒設，誰先 collect 誰決定路徑。加 `tests/conftest.py`
收斂成單一設定點後裸跑 394 → 404 passed。

**我自己寫的測試也出過假 FAIL。** `test_compose_drift_guard.py` 第一版用
`text.index("docker compose -p")` 比對原始檔，命中的是第 10 行 usage HEREDOC 裡的
說明文字而非第 61 行的實際呼叫，於是 code 正確、測試卻紅。一個把文件當成行為
讀的測試，正是該檔案要消滅的假訊號。

### 6.5 C7：sha256 相同 ≠ 已部署（本輪最有方法論價值的發現）

R2 揪出容器仍跑舊碼：

| 事實 | 值 |
|---|---|
| proc 1 StartedAt | `13:13:02Z` |
| 容器內 source mtime | `16:53:22Z`（晚 3h40m） |
| `--reload` / watcher | 無 |
| sha256 容器 vs repo | **相同** |

CPython 在 import 時綁定 module，bind mount 換檔不重載。**檔案同一性是必要非
充分**，判別式是 process 起始時間 vs source mtime。

值得記的是驗證者自己承認：**R1 它給 C7 PASS 用的正是 sha 比對，那個方法在 R2
會回假綠**——它 R1 的 PASS 只是因為當時 process 剛好啟動於那些 commit 之後。

這與本 BR 的原始根因是同一個形狀，今日第三次出現：**檢查沒涵蓋到的地方，
必然回綠，而那個綠與正確實作的綠無法區分。**

### 6.6 交互品質（記錄於此，因為它是這個機制成立的證據）

- R1 兩個 finding 我全部自行重現而非爭辯；
- 我提出的兩個反挑戰（`COMPOSE_PROJECT_NAME` 應勝過 `name:`、conftest 用
  `setdefault` 保留 override）它判定我對並撤回質疑；
- R1 它報「20 failed vs 我的 7」，查明是它自己的環境產物並主動撤回；
- conftest 的 env var 依賴是**我對自己先前宣稱的反轉**，它沒抓到。

雙向都在修正，不是驗證者橡皮圖章、也不是產出者防衛。

### 6.7 仍未覆蓋（明列，不宣稱）

- root 存在且**是**目錄但不可讀（mode 000）無測試覆蓋。
- `eb385d0` 之後的 delta 無 live-probe 覆蓋，且在容器重啟前不可能有。
