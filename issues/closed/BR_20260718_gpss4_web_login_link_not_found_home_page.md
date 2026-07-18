# BR_20260718 — GPSS4 web 會員登入層故障：login link not found on home page（兩帳號全掛）

- **狀態**: open
- **元件**: GPSS4 web headless 登入（`gpss4_set_search_scope` / `gpss4_folder_mark` 等所有 `gpss4_*` web 會員路徑共用的登入 handshake）
- **嚴重度**: high（阻斷整條 GPSS4 web 軌；TW 申請號→公開號 @AN 反查唯一路徑）
- **回報者**: 異常偵測前案檢索專案（TW-appno 復原 602 筆卡死）

## 1. 症狀

所有 `gpss4_*` web 會員工具在登入階段失敗，**兩組帳號都撞同一錯**：

```
GPSS4_DBSCOPE_RUNTIME: login failed after trying 2 account(s):
  account #0 (<account-redacted>):     login link not found on home page
  account #1 (<account-redacted>):  login link not found on home page
```

連續 2 個獨立工具（`gpss4_set_search_scope`、`gpss4_folder_mark`）同錯，非單一工具問題，是**共用登入 handshake 壞了**。

## 2. RCA 方向（待 patentmcp 端查）

`login link not found on home page` = 登入流程在 TIPO GPSS4 首頁**定位「登入」連結的選擇器失效**。最可能：

1. **TIPO 首頁 DOM 改版**——登入入口的連結文字 / href / DOM 結構變了，寫死的 selector 抓不到。
2. session/cookie 前置狀態失效導致落到非預期頁面（首頁變登入頁或錯誤頁）。

因兩帳號同錯、且錯在「找登入連結」而非「帳密錯誤」，**帳號本身無虞，問題在登入頁面解析層**。

## 3. 影響

- TW 申請號→公開號 @AN 反查（DD-95 復原路徑）**完全依賴** GPSS4 web 會員登入 → 此路不通則 602 筆 TW-appno 無法推進。
- 任何走 GPSS4 web 軌的 headless 操作（含零 API 額度的取圖/反查）全部阻斷。

## 4. 消費端現況 / workaround

- checkpoint 完好（TW-appno 已落地 168/770，未污染），登入修復後可無損續跑。
- 暫無替代路徑：這些是**申請號**（非公開號），EPO/PPUBS 單號查詢需公開號，故無法繞過 @AN 反查。只能等 GPSS4 web 登入層修復。
- 建議 patentmcp 端：重新定位 TIPO GPSS4 首頁登入連結 selector，並加一個「登入頁 DOM 快照」的 fail-fast 診斷（錯誤訊息附上實際抓到的首頁標題/URL，加速下次 RCA）。

---

## Resolution（2026-07-18，fixed）

### Live 診斷結論（授權下實連 TIPO 首頁）

用 patentmcp 自身模組的 `GPSS4Session` 常數/client（非繞道爬蟲）對現行 TIPO
首頁做 fresh anonymous GET，實測證據：
- `status=200`、`title=全球專利檢索系統`、`len=16098`（正常 16KB 首頁）。
- **舊寫死 regex `_LOGIN_LINK_RE` 現行首頁實測命中**（`PAGE=login` 連結存在）。

**→ selector 現在沒壞。** 回報時的 `login link not found` 不是 TIPO DOM 改版，
而是首頁**偶發回非標準頁面**（節流 interstitial / 錯誤頁 / cookie-jar 污染導致
落非預期頁），但**舊錯誤訊息不帶任何頁面證據**，使下次 RCA 無法區分
「DOM 改版」與「拿錙頁」。這正是本 BR §4 要求的兩件事。

### 修復（`src/patent_mcp_server/gpss4/session.py`）

1. **selector 加固**：`_LOGIN_LINK_RE` 從寫死參數順序
   `ID=\d+&SECU=-?\d+&PAGE=login&RETURN=` 改為錨定穩定輨別符
   `accserver?[^"]*\bPAGE=login\b[^"]*`——對 TIPO 重排 query 參數有韌性，仍正確
   排除同前綴的 `PAGE=register` 連結（實測：login 命中、register 排除）。
2. **fail-loud + DOM 快照**：`_fetch_login_page` 找不到登入連結時，錯誤訊息現帶
   `[status=... final_url=... len=... title=...]`——下次一看就知道拿到什麼頁，
   區分改版 vs 錯頁。

**驗證**：AST parse OK；patched 模組對實際首頁 dump 命中 login、排除 register。

### 殘留（不阻擋 close）

若需彻底端掉偶發拿錙頁，可進一步在 `_fetch_login_page` 加「非標準頁 → 重採首頁
一次」的有限 retry；但本次先交付 fail-loud 證據（未來抓到拿錙頁才能定優 retry 策略）。
現行 selector 實測可用，本 BR close。
