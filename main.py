"""發票處理器（優化版）：從 QR code 擷取發票資料。

支援 JPG、JPEG、PNG 與 PDF 檔案。從文件左上角讀取 QR code，
擷取發票號碼與金額，並將結果寫入輸出的 Markdown 報告。

相較原版的調整：
1. PDF 使用 with 關閉句柄
2. 逐檔案 try/except，失敗原因寫入報告
3. QR 欄位按語意識別（保留位置解析作為回退）
4. 去重改用 set
5. 金額改用整數分定點數，避免浮點誤差
6. 目錄排序、PDF 優先於圖片
7. 報告記錄重複與失敗明細
8. 支援遞迴子目錄
9. 輸出檔名衝突時加後綴
10. zoom 可配置，解析失敗時以更高倍率重試

QR 仍舊只從左上角 40% 區域、第一頁、第一個條碼讀取——發票格式標準化，無須全圖掃描。
"""

import argparse
import os
import re
import shutil
import sys

import fitz
import zxingcpp
from PIL import Image

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.pdf'}
INVOICE_NO_RE = re.compile(r'\d{15,25}')
AMOUNT_RE = re.compile(r'\d+(?:\.\d{1,2})?')
HTTP_AMOUNT_RE = re.compile(r'total_amount=(\d+)')
HTTP_BILL_RE = re.compile(r'bill_num=(\d+)')


def yuan_to_cents(text: str) -> int:
    """'125.10' -> 12510；'125' -> 12500。純整數運算，無浮點誤差。"""
    s = str(text).strip()
    negative = s.startswith('-')
    if negative:
        s = s[1:]
    if '.' in s:
        yuan, frac = s.split('.', 1)
        cents = int(yuan or '0') * 100 + int((frac + '00')[:2])
    else:
        cents = int(s) * 100
    return -cents if negative else cents


def cents_to_str(cents: int) -> str:
    """12510 -> '125.10'。"""
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}{cents // 100}.{cents % 100:02d}'


def pdf_to_image(pdf_path, page_num=0, zoom=2.0):
    """將 PDF 頁面轉換成 PIL Image，use 'with' 確保句柄關閉。"""
    with fitz.open(pdf_path) as doc:
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return Image.frombytes('RGB', [pix.width, pix.height], pix.samples)


def decode_qrcode(image):
    results = zxingcpp.read_barcodes(image)
    return results[0].text if results else None


def parse_qr_data(data):
    """回傳 (amount_cents, invoice_number)。整數分，不經 float。"""
    if not data:
        return None, None

    if data.startswith('http'):
        amount_match = HTTP_AMOUNT_RE.search(data)
        bill_match = HTTP_BILL_RE.search(data)
        # HTTP 格式的 total_amount 原本就是以「分」為單位
        amount_cents = int(amount_match.group(1)) if amount_match else None
        invoice_number = bill_match.group(1) if bill_match else None
        return amount_cents, invoice_number

    parts = [p.strip() for p in data.split(',')]

    # 語意識別：發票號碼為 15~25 位連續數字；金額為帶小數點的數字
    invoice_number = next((p for p in parts if INVOICE_NO_RE.fullmatch(p)), None)
    amount_cents = None
    for p in parts:
        if '.' in p and AMOUNT_RE.fullmatch(p):
            amount_cents = yuan_to_cents(p)
            break

    # 回退：原版位置解析，確保舊格式仍可讀取
    if invoice_number is None and len(parts) > 3 and parts[3]:
        invoice_number = parts[3]
    if amount_cents is None and len(parts) > 4:
        try:
            amount_cents = yuan_to_cents(parts[4])
        except ValueError:
            pass

    return amount_cents, invoice_number


def process_ticket(image):
    """只讀取影像左上角 40% 區域的第一個 QR code。"""
    width, height = image.size
    top_left = image.crop((0, 0, width * 0.4, height * 0.4))
    qr_data = decode_qrcode(top_left)
    amount_cents, invoice_number = parse_qr_data(qr_data)
    return amount_cents, invoice_number, qr_data


def process_file(file_path, zoom_levels=(2.0,)):
    ext = os.path.splitext(file_path)[1].lower()
    name = os.path.basename(file_path)

    if ext == '.pdf':
        amount_cents = invoice_number = qr_data = None
        for zoom in zoom_levels:
            image = pdf_to_image(file_path, 0, zoom)
            amount_cents, invoice_number, qr_data = process_ticket(image)
            if amount_cents is not None and invoice_number is not None:
                break
    else:
        with Image.open(file_path) as image:
            amount_cents, invoice_number, qr_data = process_ticket(image)

    return name, amount_cents, invoice_number, ext, qr_data


def unique_output_path(output_directory, invoice_number, amount_cents, ext):
    """檔名衝突時加 _1、_2 後綴，不靜默覆蓋。"""
    base = f'{invoice_number}_{cents_to_str(amount_cents)}'
    candidate = f'{base}{ext}'
    counter = 1
    while os.path.exists(os.path.join(output_directory, candidate)):
        candidate = f'{base}_{counter}{ext}'
        counter += 1
    return candidate


def iter_input_files(directory_path, recursive):
    """產出 (完整路徑, 顯示名稱)，支援遞迴。"""
    if recursive:
        for root, dirs, files in os.walk(directory_path):
            dirs.sort()
            for filename in sorted(files):
                if os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS:
                    full = os.path.join(root, filename)
                    yield full, os.path.relpath(full, directory_path)
    else:
        for filename in sorted(os.listdir(directory_path)):
            if os.path.splitext(filename)[1].lower() in SUPPORTED_EXTENSIONS:
                full = os.path.join(directory_path, filename)
                yield full, filename


def file_sort_key(display_name):
    """PDF 排在圖片前面，其餘按名稱排序，讓重複時優先保留 PDF。"""
    ext = os.path.splitext(display_name)[1].lower()
    return (0 if ext == '.pdf' else 1, display_name.lower())


def process_invoice_directory(directory_path, output_directory, zoom=2.0, recursive=True):
    os.makedirs(output_directory, exist_ok=True)
    zoom_levels = tuple(dict.fromkeys([zoom, zoom * 1.5]))

    entries = sorted(iter_input_files(directory_path, recursive), key=lambda item: file_sort_key(item[1]))

    lines = ['| 流水號 | 發票號碼 | 金額 |', '| --- | --- | ---: |']
    serial = 1
    total_cents = 0
    kept_files = {}
    duplicate_count = 0
    duplicates = []
    failures = []
    success_count = 0

    for full_path, display_name in entries:
        print(f'處理文件：{display_name}')
        try:
            name, amount_cents, invoice_number, ext, qr_data = process_file(full_path, zoom_levels)
            print(f'QR code 內容：{qr_data if qr_data else "未找到 QR code"}')

            if amount_cents is None or invoice_number is None:
                reason = 'QR 內容缺失或格式不符'
                print(f'無法解析：{reason}')
                failures.append((display_name, reason))
                continue

            if invoice_number in kept_files:
                duplicate_count += 1
                amount_str = cents_to_str(amount_cents)
                existing = next((d for d in duplicates if d[0] == invoice_number), None)
                if existing:
                    existing[3].append(display_name)
                else:
                    duplicates.append([invoice_number, amount_str, kept_files[invoice_number], [display_name]])
                print(f'跳過重複發票 {invoice_number}')
                continue

            new_name = unique_output_path(output_directory, invoice_number, amount_cents, ext)
            shutil.copyfile(full_path, os.path.join(output_directory, new_name))

            lines.append(f'| {serial} | {invoice_number} | {cents_to_str(amount_cents)} |')
            serial += 1
            total_cents += amount_cents
            kept_files[invoice_number] = display_name
            success_count += 1

            print(f'新文件名稱: {new_name}')
            print('-------------------')
        except Exception as exc:
            reason = f'{type(exc).__name__}: {exc}'
            print(f'處理失敗：{reason}')
            failures.append((display_name, reason))

    lines.append(f'|   | 合計金額 | {cents_to_str(total_cents)} |')
    lines.append(f'|   | 文件總數 | {len(entries)} |')
    lines.append(f'|   | 成功數量 | {success_count} |')
    lines.append(f'|   | 重複數量 | {duplicate_count} |')
    lines.append(f'|   | 失敗數量 | {len(failures)} |')

    if duplicates:
        lines.extend(['', '## 重複發票明細', '| 發票號碼 | 金額 | 保留檔案 | 重複檔案 |', '| --- | ---: | --- | --- |'])
        for invoice_number, amount_str, kept, repeated in duplicates:
            lines.append(f'| {invoice_number} | {amount_str} | {kept} | {"、".join(repeated)} |')

    if failures:
        lines.extend(['', '## 失敗檔案明細', '| 檔案名稱 | 原因 |', '| --- | --- |'])
        for display_name, reason in failures:
            lines.append(f'| {display_name} | {reason} |')

    print('處理摘要:')
    print(f'  總共文件: {len(entries)}')
    print(f'  成功處理: {success_count}')
    print(f'  重複檔案: {duplicate_count}')
    print(f'  失敗檔案: {len(failures)}')

    report_path = os.path.join(output_directory, 'output.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'報告已寫入: {report_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='處理 QR code 發票（優化版），支援 JPG/JPEG/PNG/PDF。')
    parser.add_argument('input_dir', nargs='?', default='./input/', help='輸入資料夾路徑')
    parser.add_argument('output_dir', nargs='?', default='./output/', help='輸出資料夾路徑')
    parser.add_argument('--zoom', type=float, default=2.0, help='PDF 渲染倍率（預設 2.0）')
    parser.add_argument('--no-recursive', action='store_true', help='不遞歸掃描子目錄')
    args = parser.parse_args()
    process_invoice_directory(
        args.input_dir,
        args.output_dir,
        zoom=args.zoom,
        recursive=not args.no_recursive,
    )
