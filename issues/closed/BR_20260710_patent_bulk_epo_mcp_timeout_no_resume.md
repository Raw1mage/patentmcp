# BR: patent_bulk(source="epo") MCP timeout 切斷 server 分頁，全撈無法完成（無斷點續跑）

- 日期：2026-07-10
- 類型：bug report（BR_20260710_epo_bulk_harvest_biblio_fanout_timeout 待補第 4 項的復發面）
- 元件：`patent_bulk` EPO 路徑（`search_dispatcher.py bulk()` → EPO biblio fan-out）
- 提出脈絡：AIOT 非接觸異常偵測 v3 精雕迴圈 D2 WiFi/CSI 補撈（total 934）

## 症狀（subagent ses_0b51c6702ffe 實測，鐵律 0 證據）

- 檢索式：WiFi/CSI 純關鍵字窄式（total 934，slice_plan 確認單切片 <2000 skip wall）
- `patent_bulk(source="epo", num=100)` 呼叫 **4 次連續 -32001 逾時**
- per-page absorb 有落地但**每次 call 被 MCP transport（~2min）切斷後，server 端分頁隨之停止**
- 淨落地 +11 筆 / ~7 分鐘，之後凍結（多輪 60s polling flat）
- 落地樣本抽查全部 on-topic——是**吞吐**卡死，不是 relevance 問題

## 根因

EPO biblio 逐件 fan-out 受 OPS 15/min 節流 → 單頁 num=100 的 fan-out 需 ~7min，
遠超 MCP transport timeout（~2min）。call 被切斷 = server 迴圈終止 = 無法靠
「重發同 call」推進（每次重發從同一 skip 重來，重複燒節流額度撈同一批）。

與前 BR 的關係：BR_20260710_epo_bulk_harvest_biblio_fanout_timeout 的
per-page absorb 修了「逾時全丟」；但待補第 4 項（節流自適應）當時標
OUT-OF-SCOPE——本 BR 即該項的實戰爆發：**沒有 MCP-timeout-safe 的斷點續跑，
EPO 大 total（>~30 筆/次）的全撈在 MCP 環境內不可能完成**。

## 修復方向（供 patentmcp 開發時參考）

1. **自動縮頁**：EPO 路徑依節流速率自動把 num cap 到 ~20（2min 內可完成的量），
   回傳 `next_skip` 讓 caller 逐頁驅動——每次 call 都在 timeout 內乾淨返回。
2. 或 **背景 job 模式**：bulk 呼叫立即返回 job id，harvest 在 server 端獨立跑，
   另給 `bulk_status(job_id)` 查進度（架構較大，另議）。
3. 短期 workaround（不動 code）：caller 以 num≤20 逐頁呼叫 + 自帶 skip 遞增。

## Workaround 實戰驗證（2026-07-10，subagent ses_0b50f6509ffe）

**num=20 逐頁驅動決定性有效**：同一條 D2 檢索式（total 934）以 num=20 從
skip=0 → 680 全程**零 -32001 逾時**，D2 撈至 exhausted 淨增 565 筆；
D4 收窄式 slice-1 同法again落地 191 筆。證實 num=100 逾時凍結的根因就是
「單頁 fan-out 時間 > MCP transport timeout」。在修復方向 1（自動縮頁）
落地前，**num≤20 是 EPO bulk 的標準操作**，應寫入 patentworks KB 來源梯。

## 驗收

- EPO 全撈 total ~1000 的檢索式可在 MCP 環境內跑完（無單次 call 逾時）
- `next_skip` / `exhausted` 語義在 EPO 路徑真實可用（每 call 乾淨返回）

## 影響中的工作

- D2 WiFi/CSI（934）卡在 +11
- D4 A61B5/0205 收窄式（2370）已拍板全撈，同樣會撞牆——量更大

---

## Resolution（2026-07-18，fixed — 修復方向 1「自動縮頁」已落地）

**現況核對**：`src/patent_mcp_server/search_dispatcher.py` EPO bulk 路徑已實作
MCP-timeout-safe 的自動縮頁 + 斷點續跑：
- `_EPO_CALL_BIBLIO_CAP = 20`（:938）：每 call 的 biblio fan-out 上限 cap 到 20，
  確保單次呼叫在 MCP transport timeout（~2min）內乾淨返回（對齊 BR 修復方向 1 與
  workaround 實戰的 num≤20 決定性有效）。
- `target = min(spec.num, _EPO_CALL_BIBLIO_CAP, _EPO_SKIP_WALL)`（:989）：caller 帶更大
  num 時靠 `next_skip` 逐 call 續跑，不再單 call 燒節流撈同一批。
- envelope 帶 `next_skip` / `exhausted` / `page_capped`（:1096-1102）：`page_capped=true`
  提示 caller 帶 `next_skip` 再呼叫，不誤判 total 已撈完；COALESCE upsert 冪等。
- `_EPO_SKIP_WALL = 2000`（:927）deep-paging wall 明示。

**KB 同步**：patentworks SKILL.md §197-198 已寫入 EPO 大母數自動切片工作流
（`slice_plan` planning-only + 逐片 `next_skip` 續撈 + `SLICE_INEFFECTIVE` 守恆自證）
與兩源通用續撈語義。

驗收（BR §驗收）達成：EPO 全撈可在 MCP 環境內逐頁乾淨返回、`next_skip`/`exhausted`
真實可用。修復方向 2（背景 job 模式）當時標「架構較大，另議」，非本次 scope。本 BR close。
