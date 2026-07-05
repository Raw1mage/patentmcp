# BR_20260706 — patentmcp WebDAV credential bootstrap drifts from R14.6 (no MCP-rail issuance)

**Status**: RESOLVED (2026-07-06, patentmcp session)
**Severity**: High (blocks R14.6 conformance; webdav credential un-bootstrappable on no-gateway / multi-user hosts)
**Scope**: patentmcp webdav working-cache (R14 conformance)
**Source**: fleet plan `opencode/plans/mcp_webdav-fleet-conformance` (deep-recon ses_0ccf3abc9ffe + governance session 2026-07-06)
**Fleet SSOT**: `opencode/specs/mcp-integration-standard/standard.md` §R14 + §12 readiness matrix

## 現象(含硬證據)

patentmcp 有完整的 class-2 WebDAV mount，但 **credential bootstrap 缺 MCP-rail 簽發入口**，與 docxmcp reference（R14.6）漂移：

- class-2 DAV 實作齊全：`src/patent_mcp_server/_dav.py`（429 行，PROPFIND/PUT/DELETE handlers @ `:39`）
- N:M export 一等公民：`cache_export(subject,target)` @ `src/patent_mcp_server/patents.py:3066`
- `cache_provision` @ `src/patent_mcp_server/patents.py:2999`
- **credential 只走 HTTP path**：`src/patent_mcp_server/_auth_provider.py:7` — per-owner credential 由 HTTP Basic-auth 路徑簽發
- **缺 MCP-rail `issue_webdav_credential`**：grep 整個 repo 對 `issue_webdav_credential` 全空命中。socket==capability 的 inline 簽發路徑不存在。

後果：chicken-and-egg 未解 —— 要拿 webdav credential 得先有 Basic auth credential。在無 gateway、多用戶隔離的 host 上，agent 持有 MCP socket 卻無法 bootstrap 出 webdav 密碼。

## RCA

patentmcp 的 `webdav-r13-refactor` 對齊了 docxmcp 的 **mount / wire / lifecycle**（class-2 DAV、pass-by-value、token model 都到位），但**沒跟上 docxmcp 後續補的 socket-rail credential 簽發**。docxmcp 在 commit `54eac2e`（`bin/mcp_server.py:2641` + `_mcp_registry.py:2921` + `_auth_provider.py:196`）加了 opt-in `issue_webdav_credential` flag，把「持有 MCP socket 即可簽發 webdav credential」定為 R14.6 reference 語義；patentmcp 停在只有 HTTP 簽發的舊狀態。這是 downstream 追隨 reference 時的**時間差漂移**，非設計錯誤。

## 建議修復（對映 fleet plan tasks §3.1–3.6）

1. **R14.6（核心）**：port docxmcp 的 opt-in `issue_webdav_credential` flag 到 `cache_provision`（`patents.py:2999`）。用 patentmcp 自己的 `_auth_provider` mint/rotate；socket==capability inline 簽發；**default payload byte-identical**（flag 省略時完全不變 —— 天条 11 no-fallback，禁止 silent credential）。schema 註冊處對照 docxmcp `_mcp_registry.py:2921`。
2. **R14.4**：驗證/補 `_dav.py` PROPFIND/PUT/DELETE 對 token dir 外路徑的 path-traversal 拒絕。
3. **R14.5**：補 per-host `AUTH_PROVIDER=builtin`（或等價）provision 設定到 patentmcp 部署設定（compose 等）。
4. **R14.7**：確認/實作「未 provision → stage-inline + UDS GET」fallback（loud 不 silent）；若無視為 gap 補上。
5. **測試（DD-5 test-verified，關鍵）**：延伸 `tests/test_cache_tools.py`，mirror docxmcp `test_mcp_cache_credential_issue.py` 的真 dispatch + 真 auth provider + PBKDF2 bar，測簽發 + rotate + default byte-identical。
6. **回歸**：跑既有 `test_dav.py` + `test_cache_tools.py` 無回歸。

> **Governance note**：本 BR 由 opencode 治理 session 發出，**未在該 session 動 patentmcp code**。（先前一次跨-session code 改造已被使用者叫停並 `git checkout` 回退 —— 跨 repo code 改造應在 patentmcp 自己的 session 做，以此 BR + fleet plan `tasks.md §3` / `handoff.md` / `spec.md` 為契約。）

## 影響範圍

- patentmcp webdav 交付在**無 gateway / 多用戶 host** 無法 bootstrap credential（實務阻塞）。
- 對已有 Basic auth 的單用戶場景可運作 —— 故非全毀，但不符 R14.6 fleet 一致性。
- 打擊半徑：`cache_provision` dispatch + auth provider + schema registry；default payload 必須保持不變以免影響既有 caller。

## 驗證手段

- `patentmcp .venv/bin/python -m pytest tests/test_cache_tools.py tests/test_dav.py -x` 全綠。
- 新 credential test：`issue_webdav_credential=true` 回 rotated credential；省略 flag 時 payload byte-identical（diff 為空）。
- 對照 docxmcp `test_mcp_cache_credential_issue.py`（3 passed）的驗證強度。
- fleet plan §12 矩陣 patentmcp 列從 `⚠️ handoff` 升到 test-verified `✅` 後才算 close。

## 處置紀錄 2026-07-06(本 repo session)

- **R14.6 已落地**:`cache_provision` 新增 opt-in `issue_webdav_credential: bool = False`(`src/patent_mcp_server/patents.py:3001`)。flag=true 時 mint-or-rotate 該 cache 的 Basic credential 並回 cleartext 一次;flag 省略時 payload byte-identical(以 `test_default_payload_byte_identical_without_flag` 全 dict 相等固化)。port 自 docxmcp reference commit `54eac2e` 語義(rotate-on-call、socket==capability)。
- **R14.4 已驗證**:`TokenStore._safe_target`(`_token_store.py:263`)覆蓋所有 DAV 寫讀路徑(write_file/blob_path/stat_entry/list_dir/mkdir/move);回填 4 個 traversal 拒絕 regression tests(PUT `../`、PUT 絕對路徑、DELETE `../victim`、PROPFIND `../`)於 `tests/test_dav.py`。
- **R14.5 已註明**:patentmcp auth provider 為 builtin-only(token-store-backed Basic auth,無 gateway-backed 變體,無需 env switch);compose 註解明示 named volume + DAV face = per-host provisioning(`docker-compose.yml`)。
- **R14.7 已確認**:`stage_file` 為 typed `TOOL_LANDED` 明示轉導(loud 非 silent),stage-inline 語義由 DAV PUT + `/files/{token}/blob/{rel}` UDS GET 承接(`_http_app.py:409`)。
- **測試**:新增 3 credential tests(rotate/byte-identical/owner-required)+ 4 traversal tests;`test_cache_tools.py`+`test_dav.py`+`test_token_store_cache.py` 40 passed;全套 143 passed 無回歸。
- **文件同步**:mcp.json instructions 補 R14.6 用法(rotate 警語);`specs/architecture.md` WebDAV 段 + Sync Note 同步。
- **殘留(opencode repo 動作,非本 repo)**:fleet plan `mcp_webdav-fleet-conformance` tasks §3.1–3.6 tick + §12 矩陣 patentmcp 列升 test-verified ✅;conformance vectors(§5)後續收斂。
