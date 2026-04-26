# 發票處理器

從 QR code 擷取發票資料的工具，支援 JPG、JPEG、PNG 與 PDF 檔案。

## 功能特色

- 自動從文件左上角讀取 QR code
- 擷取發票號碼與金額
- 支援多種檔案格式
- 產生 Markdown 報告與統計摘要
- 避免重複發票處理

## 系統需求

- Python 3.7+
- Windows 作業系統

## 安裝步驟

1. 執行 `setup.bat` 安裝 Python 依賴：
   ```
   setup.bat
   ```

2. 將發票檔案放入 `input/` 資料夾

## 使用方式

### 方法一：雙擊執行（推薦）

1. 編輯 `run.bat` 中的輸入/輸出路徑（預設為 `./input/` 與 `./output/`）
2. 雙擊 `run.bat` 開始處理

### 方法二：命令列執行

```bash
python main.py [輸入資料夾] [輸出資料夾]
```

範例：
```bash
python main.py ./input ./output
```

## 輸出結果

- 處理後的檔案會複製到輸出資料夾，並重新命名為 `{發票號碼}_{金額}.ext`
- 產生 `output.md` Markdown 報告，包含：
  - 處理成功的發票清單
  - 合計金額
  - 處理統計（總數、成功、重複、失敗）

## 支援格式

- JPG / JPEG
- PNG
- PDF

## 注意事項

- 確保 QR code 位於文件左上角區域
- 支援兩種 QR code 格式：
  - HTTP 連結格式：`total_amount=12345&bill_num=67890`
  - 逗號分隔格式：`data1,data2,data3,invoice_num,amount`
- 失敗檔案不會被複製，但會記錄在統計中

## 故障排除

- 若出現模組錯誤，請先執行 `setup.bat`
- 檢查 Python 版本是否為 3.7+
- 確保輸入資料夾存在且包含支援的檔案格式