"""發票處理器：從 QR code 擷取發票資料。

支援 PDF 與常見點陣圖格式（JPG/JPEG/PNG/GIF/BMP/TIFF/WEBP 等，
凡 Pillow 可開啟者皆支援），擷取發票號碼與金額並產生 Markdown 報告。
點陣圖解碼以 Pillow 為前端，格式無關；內嵌圖片的格式由 PDF 決定，
不假設為 PNG。

PDF 讀取策略（兩條路徑）：
  主路徑（pypdf，輕量必需）：直接從 PDF 第一頁提取所有內嵌圖片並逐張解碼 QR。
    不假設 QR 的尺寸與位置，整張圖片交給解碼器，解析度不足時放大重試。
    无需渲染整頁，速度快且依賴極小。
  兜底路徑（pypdfium2，選用懶加載）：若內嵌圖片解不出 QR（例如 QR 為矢量繪製），
    才渲染整頁並整頁解碼。需另外安裝：pip install pypdfium2
  兩條路徑都只讀第一頁、只取第一個解出的 QR，不做多頁或多結果掃描。

其餘設計：
  - 逐檔案 try/except，失敗原因寫入報告
  - QR 欄位按語意識別（保留位置解析作為回退）
  - 去重改用 set
  - 金額改用整數分定點數，避免浮點誤差
  - 目錄排序、PDF 優先於圖片
  - 報告記錄重複與失敗明細
  - 支援遞迴子目錄
  - 輸出檔名衝突時加後綴
"""

import argparse
import io
import os
import re
import shutil

from PIL import Image
from pypdf import PdfReader
import zxingcpp

SUPPORTED_EXTENSIONS = {
    '.jpg', '.jpeg', '.jpe', '.png', '.gif', '.bmp',
    '.tif', '.tiff', '.webp', '.pdf',
}
INVOICE_NO_RE = re.compile(r'\d{15,25}')
AMOUNT_RE = re.compile(r'\d+(?:\.\d{1,2})?')
HTTP_AMOUNT_RE = re.compile(r'total_amount=(\d+)')
HTTP_BILL_RE = re.compile(r'bill_num=(\d+)')

_PYPDFIUM2_WARNED = False
_pypdfium2 = None


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


def decode_qrcode(image, scales=(1, 2, 4)):
    """解碼影像的第一個條碼，回溯所有影格與放大重試。

    不裁剪固定區域，QR 出現在影像任何位置都能讀取；
    不假設影像格式，任何 Pillow 可開啟的格式皆可。
    多影格格式（如動畫 GIF、多頁 TIFF）會逐一檢查。
    scales 為整數倍放大序列，1 倍成功就不做後續重試。
    """
    frame_count = getattr(image, 'n_frames', 1)
    for frame_index in range(frame_count):
        if frame_index:
            try:
                image.seek(frame_index)
            except (EOFError, ValueError):
                break
        for scale in scales:
            target = image
            if scale != 1:
                target = image.resize(
                    (image.width * scale, image.height * scale), Image.LANCZOS
                )
            results = zxingcpp.read_barcodes(target)
            if results:
                return results[0].text
    return None


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


def decode_from_image(image):
    """解碼整張影像的 QR，回傳 (qr_data, amount_cents, invoice_number)。

    不假設 QR 位置與解析度，僅取第一個解出的條碼。
    """
    qr_data = decode_qrcode(image)
    amount_cents, invoice_number = parse_qr_data(qr_data)
    return qr_data, amount_cents, invoice_number


def decode_pdf_embedded_images(pdf_path, page_num=0):
    """主路徑：從 PDF 頁面提取內嵌圖片並逐張解碼 QR。

    不假設 QR 的尺寸或位置：實測內嵌圖從 47x47 到 650x433 都有，
    可能是獨立的 QR 圖，也可能 QR 只是較大圖片的一角。
    逐張整圖解碼，解析度不足時由 decode_qrcode 放大重試。
    """
    reader = PdfReader(pdf_path)
    if page_num >= len(reader.pages):
        return None, None, None
    page = reader.pages[page_num]

    for image_file in page.images:
        try:
            with Image.open(io.BytesIO(image_file.data)) as image:
                qr_data = decode_qrcode(image)
                amount_cents, invoice_number = parse_qr_data(qr_data)
            if amount_cents is not None and invoice_number is not None:
                return qr_data, amount_cents, invoice_number
        except Exception:
            continue
    return None, None, None


def render_pdf_page(pdf_path, page_num=0, zoom=2.0):
    """兜底路徑：用 pypdfium2 渲染整頁成 PIL Image。

    pypdfium2 為選用依賴，懶加載；未安裝時回傳 None 並提示一次。
    安裝方式：pip install pypdfium2
    """
    global _pypdfium2, _PYPDFIUM2_WARNED
    if _pypdfium2 is None:
        try:
            import pypdfium2
            _pypdfium2 = pypdfium2
        except ImportError:
            if not _PYPDFIUM2_WARNED:
                print('提示：內嵌圖片未能解碼，且未安裝 pypdfium2；'
                      '若需渲染兜底請執行 pip install pypdfium2')
                _PYPDFIUM2_WARNED = True
            return None

    pdf = _pypdfium2.PdfDocument(pdf_path)
    page = pdf[page_num]
    return page.render(scale=zoom).to_pil()


def process_file(file_path, zoom_levels=(2.0,)):
    ext = os.path.splitext(file_path)[1].lower()
    name = os.path.basename(file_path)

    if ext == '.pdf':
        # 主路徑：直接提取內嵌 QR 圖片
        qr_data, amount_cents, invoice_number = decode_pdf_embedded_images(file_path)

        # 兜底：渲染整頁後整頁解碼（QR 為矢量繪製或無內嵌圖時）
        if amount_cents is None or invoice_number is None:
            for zoom in zoom_levels:
                image = render_pdf_page(file_path, 0, zoom)
                if image is None:
                    break
                qr_data, amount_cents, invoice_number = decode_from_image(image)
                if amount_cents is not None and invoice_number is not None:
                    break
    else:
        with Image.open(file_path) as image:
            qr_data, amount_cents, invoice_number = decode_from_image(image)

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
    parser = argparse.ArgumentParser(
        description='處理 QR code 發票，支援 PDF 與常見點陣圖格式。'
    )
    parser.add_argument('input_dir', nargs='?', default='./input/', help='輸入資料夾路徑')
    parser.add_argument('output_dir', nargs='?', default='./output/', help='輸出資料夾路徑')
    parser.add_argument('--zoom', type=float, default=2.0, help='PDF 渲染倍率（僅兜底路徑使用，預設 2.0）')
    parser.add_argument('--no-recursive', action='store_true', help='不遞歸掃描子目錄')
    args = parser.parse_args()
    process_invoice_directory(
        args.input_dir,
        args.output_dir,
        zoom=args.zoom,
        recursive=not args.no_recursive,
    )
