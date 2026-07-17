# Spec: patentmcp_gpss4-login-account-rotation

## Purpose

`GPSS4Session` 對 gpss4 會員登入時，SHALL 支援 N 組成對登入帳號池；當當前帳號登入失敗（CAPTCHA 重試耗盡 / 帳密被拒 / HTTP 錯誤）時，SHALL 自動輪替至下一組未失敗帳號重試登入；全部帳號登入失敗時 SHALL 以 `GPSS4LoginError` fail-fast，不 fallback。rotation 對呼叫端透明（`login()`/`ensure_logged_in()`/`get()` 簽名不變）。

## Requirements

### Requirement: 多帳號登入輪替

系統 SHALL 支援以編號式 env（`GPSS4_USERNAME[_N]`/`GPSS4_PASSWORD[_N]`）設定的 N 組帳號池，並在當前帳號登入失敗時輪替至下一未失敗帳號重試。

#### Scenario: 主帳號登入失敗自動換第二帳號

- **WHEN** 帳號1 完整登入序列（含 max_captcha_retry 次重試）仍失敗
- **THEN** 標記帳號1 本 process 失敗、游標移帳號2、以帳號2 重跑登入序列並回其結果

#### Scenario: 全部帳號登入失敗 fail-fast

- **WHEN** 帳號池所有帳號登入皆失敗
- **THEN** raise `GPSS4LoginError`，訊息含 `tried N account(s)`，不 fallback

### Requirement: 向後相容與可擴充設定

系統 SHALL 以 `GPSS4_USERNAME`/`GPSS4_PASSWORD`（無後綴）為帳號1，連續掃描 `_2`/`_3`… 至缺號止；成對完整（user 與 pass 皆非空）才納入池。單帳號設定行為與改動前一致。

#### Scenario: 相容舊單帳號設定

- **WHEN** 只設定 `GPSS4_USERNAME`/`GPSS4_PASSWORD`、未設 `_2`
- **THEN** 帳號池 = 該單帳號，行為與改動前一致

### Requirement: 只對登入失敗輪替（防誤換）

系統 SHALL 僅在登入失敗時輪替帳號；登入成功後的 session 過期 re-login SHALL 用當前有效帳號，不輪替。

#### Scenario: session 過期 re-login 不換帳號

- **WHEN** 已登入帳號的 session 過期、`get()` 觸發自動 re-login
- **THEN** 用當前有效帳號重新登入，不切換到其他帳號

## Acceptance Checks

- [ ] 編號式帳號池解析（缺號即停、成對完整才納入）
- [ ] 退讀單帳號相容
- [ ] 主帳號登入失敗 → 換第二帳號成功
- [ ] 全部登入失敗 → GPSS4LoginError（tried N）
- [ ] session 過期 re-login 用當前帳號不誤換
- [ ] 全套既有測試不回歸
