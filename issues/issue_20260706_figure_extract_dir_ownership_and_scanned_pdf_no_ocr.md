# ISSUE (工具層): 取圖落地路徑兩個 friction — patentdb 目錄 root 擁有權 + WO 純掃描件無 OCR fallback

**Date**: 2026-07-06
**Status**: Open
**Priority**: Medium
**Target**: `skills/patentworks/scripts/figure_extract.py` + patentdb 目錄佈建流程
**Reporter**: AI Agent(驗證 A 取圖子代理揭出)
**Source**: BR_20260628 驗證 A 回歸(3 件跨路徑取圖)

---

## 1. Friction 1 — patentdb/<國>/<案>/ 目錄 root 擁有權

**現象**:US10096234B1 / WO2018151004A1 的 `patentdb/<國>/<案>/` 目錄為 root 擁有(uid=root),取圖子代理寫 PNG 時初次 EACCES,改用 `sudo` 落地並 `chown pkcs12` 才成功。

**RCA**:patentdb 目錄由容器側(docker,root)佈建;host 側腳本以 pkcs12 身分寫入即權限衝突。`docker-compose.yml` 剛加的 `./patentdb:/patentdb` bind mount(commit 7a1eff5)讓容器與 host 共享單一庫,但未統一擁有權/權限模型。

**影響範圍**:任何 host 側取圖/落地腳本寫既有容器建的案目錄都會撞 EACCES;容器化流程若無 sudo(無互動 shell)會直接失敗。

**建議修復**:佈建 patentdb 案目錄時統一 uid(容器 user 對齊 host uid,或目錄 g+ws + 共享 group);或 figure_extract.py 落地前偵測 EACCES 給明確提示而非靜默失敗。

## 2. Friction 2 — WO 純掃描 PDF(無文字層)無 OCR / 封面圖 fallback

**現象**:WO2018151004A1 是純掃描 PDF(33 頁 33 張 CCITT 內嵌圖,無文字層)。`figure_extract.py` 回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT` —— text-based FIG.1 定位器對無文字層天然失效。子代理**依 BR_20260628 委派契約不宣告無圖**,改人工視覺確認封面(WIPO 封面內含代表系統圖)+ pdftoppm 渲染落地。

**RCA**:`figure_extract.py` 的定位器依賴 PDF 文字層找 "FIG. 1" 錨點;掃描件無文字層 → 定位器無輸入。目前靠 AI 視覺兜底,非自動化。host 無 tesseract。

**影響範圍**:所有純掃描 PDF(多為早期公開案 / 部分 WO/JP)取代表圖都會落到人工視覺兜底,無法批量自動化。

**建議修復**:對 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT` 增補 fallback ——(a) OCR(tesseract)找 FIG.1 文字錨點;或(b)「封面內嵌圖」啟發式(WIPO/EPO 封面常含代表圖,取 page 1 最大 image XObject)。至少讓 figure_extract.py 對掃描件回一個候選頁而非全空。

## 4. 驗證手段

- Friction 1:以 host uid 對既有容器建的案目錄跑 figure_extract.py 落地,斷言無 EACCES。
- Friction 2:對 WO2018151004A1(純掃描)跑增補後的 figure_extract.py,斷言回非空候選代表圖頁,無需人工視覺。

---

## 關聯
- 揭出來源:BR_20260628 驗證 A(委派契約回歸,3/3 取圖通過)。這兩個 friction 不影響委派契約正確性,是取圖工具鏈的獨立缺陷。
