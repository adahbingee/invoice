# 發票處理器

從 QR code 擷取發票資料的工具，支援 PDF 與常見點陣圖格式。

## 功能特色

- 從 PDF 內嵌圖片直接讀取 QR code（輕量、快速）
- 內嵌圖片格式無關：PNG、JPEG、GIF、BMP、TIFF、WEBP 等凡 Pillow 可開啟者皆支援，不假設為 PNG
- 擷取發票號碼與金額，以整數分計價避免浮點誤差
- 支援多種檔案格式與遞迴子目錄
- 產生 Markdown 報告，含統計、重複與失敗明細
- 避免重複發票處理，PDF 優先於圖片

## 系統需求

- Python 3.7+
- Windows 作業系統

## 安裝步驟

1. 執行 `setup.bat` 安裝 Python 依賴（`pypdf`、`Pillow`、`zxing-cpp`）：
   ```
   setup.bat
   ```
2. 將發票檔案放入 `input/` 資料夾

## PDF 讀取策略

程式讀取 PDF 時有兩條路徑：

### 主路徑：pypdf 提取內嵌圖片（預設，無須額外設定）

程式直接用 `pypdf` 把 PDF 第一頁的內嵌圖片逐張取出解碼，**不渲染整頁**，
因此速度快、依賴極小。實測本批 59/59 份發票都能由此路徑成功解析。

此路徑不假設 QR 的固定尺寸或位置：內嵌圖可能從 47×47 到 650×433 不等，
QR 可能是獨立圖片，也可能只是較大圖片的一角。解碼器對整張圖片掃描，
解析度不足時自動放大重試。

### 兜底路徑：pypdfium2 渲染整頁（選用）

若遇到 QR 為矢量繪製、或沒有內嵌圖片的 PDF，主路徑會失敗。此時程式會嘗試
渲染整頁並整頁解碼。這條路徑需要另外安裝可選依賴：

```bash
pip install pypdfium2
```

未安裝時不影響一般使用；僅在需要兜底時於終端機提示一次。若要指定渲染倍率，
可在命令列加 `--zoom`（預設 2.0，僅兜底路徑使用）。

## 使用方式

### 方法一：雙擊執行（推薦）

1. 編輯 `run.bat` 中的輸入/輸出路徑（預設為 `./input/` 與 `./output/`）
2. 雙擊 `run.bat` 開始處理

### 方法二：命令列執行

```bash
python main.py [輸入資料夾] [輸出資料夾] [--zoom 倍率] [--no-recursive]
```

範例：
```bash
python main.py ./input ./output
python main.py ./input ./output --zoom 3.0        # 兜底渲染用較高倍率
python main.py ./input ./output --no-recursive    # 不掃描子目錄
```

## 輸出結果

- 處理後的檔案會複製到輸出資料夾，並重新命名為 `{發票號碼}_{金額}.ext`
- 產生 `output.md` Markdown 報告，包含：
  - 處理成功的發票清單
  - 合計金額
  - 處理統計（總數、成功、重複、失敗）
  - 重複發票明細（發票號碼、金額、保留檔案、重複檔案）
  - 失敗檔案明細（檔案名稱與錯誤原因）

## 支援格式

- PDF（內嵌圖片可為任意 Pillow 可解碼的格式）
- JPG / JPEG / JPE
- PNG / GIF / BMP
- TIFF / TIF（含多頁）
- WEBP

點陣圖解碼以 Pillow 為前端，格式無關；內嵌圖片的格式由 PDF 本身決定，
程式不假設其為 PNG。多影格格式（動畫 GIF、多頁 TIFF）會逐一檢查每個影格。

## 注意事項

- 圖片檔案（JPG/JPEG/PNG）與 PDF 均以整張影像解碼 QR，不限制位置；
  解析度過低時會自動放大重試，但過度模糊仍可能無法辨識
- 僅讀取 PDF 第一頁，並取第一個解出的 QR；不以多頁或多條碼掃描的方式猜測
- PDF 檔案偏好內嵌 QR 圖片；若無，才會走整頁渲染兜底
- 支援兩種 QR code 格式：
  - HTTP 連結格式：`total_amount=12345&bill_num=67890`（金額單位為分）
  - 逗號分隔格式：`data1,data2,data3,invoice_num,amount`
- 失敗檔案不會被複製，但會記錄在報告的失敗明細中

## 故障排除

- 若出現模組錯誤，請先執行 `setup.bat`
- 若終端機提示「未安裝 pypdfium2」且發票解析失敗，執行 `pip install pypdfium2` 啟用兜底
- 檢查 Python 版本是否為 3.7+
- 確保輸入資料夾存在且包含支援的檔案格式
