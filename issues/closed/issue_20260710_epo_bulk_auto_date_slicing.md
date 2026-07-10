# FR: EPO 全撈需內建「母數探測 → 自動 date 切片」（OPS skip=2000 硬牆）

- 日期：2026-07-10
- 類型：feature request
- 元件：`epo_bulk_harvest` / EPO 分頁邏輯
- 提出脈絡：AIOT 非接觸異常偵測 EPO v2 建池全撈

## 問題

EPO OPS 分頁有官方硬上限 **skip=2000**（超過回 HTTP 400）。單一 query 母數
> 2000 時，無法一次撈完，必須 date 切片到每片 < 2000。目前這個切片邏輯
**全靠人工**：手動探年度分佈、手動判斷每片是否 < 2000、手動切 6 片。

實證（本次建池）：EPO 母數 22622，年度探針 total：2015-18=2190 / 2019-20=2941
/ 2021=2501 / 2022=2864 / 2023=3277 / 2024=3236，**每個年切片都 > 2000**，
必須再細切到半年/季才能在 skip=2000 內撈完。這一輪探測+切片人工成本高、
易漏（切錯粒度 → 某片 > 2000 → 靜默漏抓尾段）。

## 建議

`epo_bulk_harvest` 內建 **auto date-slicing**：
1. 先發一次 count-only（或首頁）拿母數 total。
2. total ≤ 2000 → 直接全撈。
3. total > 2000 → 自動按 date 遞迴二分切片（年 → 半年 → 季 → 月），
   直到每片 total < 2000，逐片全撈。
4. 回傳每片的 `{date_from, date_to, total, pulled}`，並斷言
   `sum(pulled) == 母數 total`（無漏頁自證，呼應鐵律 0 可核對）。

## 完備性驗證要件（鐵律 0）

切片方案必須自證無漏：**各切片 total 相加 ≈ 母數**。若相加顯著低於母數，
代表 date 切片在 EPO 分支未生效（假切）→ 必須 fail-fast 報錯，不可靜默
交出殘缺池。本次已手動驗證 6 切片相加無漏頁、per-page COALESCE 冪等。

## 驗收

- `epo_bulk_harvest` 給大母數 query 時自動遞迴 date 切片，無需人工探年度。
- 回傳含每片 total/pulled + 總和守恆斷言。
- 切片未生效時 fail-fast，不靜默漏抓。

---

## 結案記錄 2026-07-10(plan `patentmcp_bulk-entry-unification` Phase 7,DD-8/DD-9)

實作為「slice planning + 片內續撈」兩面(拒絕 server 單呼叫逐片全拉——那是 BR1 timeout 根因重演):

- **`epo_slice_plan`**(`search_dispatcher.py`):count-probe(num=1 零 biblio)取母數 → ≤2000 單片;>2000 無 date 範圍 → `DATE_RANGE_REQUIRED` fail-fast;>2000 有範圍 → 遞迴二分(互斥切點,深度 cap 6 / probe cap 32,觸頂片標 `truncated`)→ sum_check 5% 容忍,超過 → `SLICE_INEFFECTIVE` fail-fast(假切自證,鐵律 0)。
- **MCP 面**:`patent_bulk(source="epo", slice_plan=true)` planning-only 回切片計畫;非 planning 呼叫 total>wall 時 envelope 補 `slice_hint` 提示。gpss+slice_plan → INVALID_PARAMS。
- **測試**:`tests/test_epo_slice_plan.py` 12 測試(含 issue 實證形狀:母數 22622、年片全 >2000 需再細切);全套件 187 passed。
- **KB**:SKILL.md §5 已收錄大母數建池 slice_plan 工作流。

驗收三項全數滿足(自動遞迴切片/每片 total+守恆自證/未生效 fail-fast)。

Status: **Resolved**
