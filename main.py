"""發票處理器：從 QR code 擷取發票資料。

支援 JPG、JPEG、PNG 與 PDF 檔案。從文件左上角讀取 QR code，擷取
發票號碼與金額，並將結果寫入輸出的 Markdown 報告。
"""

import argparse
import os
import re
import shutil
import zxingcpp
import fitz
from PIL import Image


def pdf_to_image(pdf_path, page_num=0):
    """將 PDF 頁面轉換成 PIL Image。"""
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_num)
    zoom = 2
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img

def decode_qrcode(image):
    """從影像讀取 QR code 資料。

    若找到條碼，則回傳解碼文字；否則回傳 None。
    """
    results = zxingcpp.read_barcodes(image)
    if results:
        return results[0].text
    return None

def process_ticket(image: Image):
    """從票據影像擷取發票金額與號碼。

    本函式會裁切影像左上方 40% 區域，並從該區域解碼 QR code。
    """
    width, height = image.size
    top_left_area = (0, 0, width * 0.4, height * 0.4)
    top_left_image = image.crop(top_left_area)

    qr_code_data = decode_qrcode(top_left_image)
    amount = None
    invoice_number = None

    if qr_code_data:
        if qr_code_data.startswith("http"):
            amount_re = re.compile(r'total_amount=(\d+)')
            amount_match = amount_re.search(qr_code_data)
            if amount_match:
                amount = int(amount_match.group(1)) / 100

            invoice_number_re = re.compile(r'bill_num=(\d+)')
            invoice_number_match = invoice_number_re.search(qr_code_data)
            if invoice_number_match:
                invoice_number = invoice_number_match.group(1)
        else:
            split_data = qr_code_data.split(',')
            if len(split_data) > 4:
                try:
                    amount = float(split_data[4])
                except ValueError:
                    amount = None

            if len(split_data) > 3:
                invoice_number = split_data[3]

    return amount, invoice_number, qr_code_data


def process_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.pdf':
        image = pdf_to_image(file_path, 0)
    else:
        image = Image.open(file_path)

    amount, invoice_number, qr_code_data = process_ticket(image)
    return os.path.basename(file_path), amount, invoice_number, ext, qr_code_data


def save_processed_file(src_path, output_directory, invoice_number, amount, ext):
    """將處理後的檔案複製到輸出目錄，並使用新檔名。"""
    new_file_name = f"{invoice_number}_{amount:.2f}{ext}"
    new_file_path = os.path.join(output_directory, new_file_name)
    shutil.copyfile(src_path, new_file_path)
    return new_file_name


def process_invoice_directory(directory_path, output_directory):
    """處理輸入目錄中的所有支援發票檔案。

    本函式會掃描支援的副檔名，解碼 QR code 資料，將成功處理的檔案
    複製至輸出目錄，並產生 Markdown 結果摘要。
    """
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    markdown_table  = "| 流水號 | 發票號碼 | 金額 |\n| --- | --- | ---: |\n"
    serial_number   = 1
    total_amount    = 0
    invoice_numbers = []
    total_files     = 0
    success_count   = 0
    duplicate_count = 0
    failed_count    = 0

    supported_extensions = {'.jpg', '.jpeg', '.png', '.pdf'}
    # 只處理支援的副檔名檔案

    for file in os.listdir(directory_path):
        ext = os.path.splitext(file)[1].lower()
        if ext not in supported_extensions:
            continue

        total_files += 1
        file_path = os.path.join(directory_path, file)
        print(f"處理文件：{file_path}")

        file_name, amount, invoice_number, ext, qr_code_data = process_file(file_path)

        print(f"QR code 內容：{qr_code_data if qr_code_data else '未找到 QR code'}")

        # 若任一項資料缺失，則無法安全記錄該發票
        if amount is None or invoice_number is None:
            print(f"無法解析 QR code 或缺少資料：{file_name}")
            print()
            failed_count += 1
            continue

        if invoice_number in invoice_numbers:
            print(f'跳過重複發票 {invoice_number}\n')
            duplicate_count += 1
            continue

        new_file_name = save_processed_file(file_path, output_directory, invoice_number, amount, ext)

        markdown_table += f"| {serial_number} | {invoice_number} | {amount:.2f} |\n"
        serial_number  += 1
        total_amount   += amount
        success_count  += 1
        invoice_numbers.append(invoice_number)

        print(f"新文件名稱: {new_file_name}")
        print('-------------------')

    total_amount = round(total_amount, 2)
    markdown_table += f"|   | 合計金額 | {total_amount} |\n"
    markdown_table += f"|   | 文件總數 | {total_files} |\n"
    markdown_table += f"|   | 成功數量 | {success_count} |\n"
    markdown_table += f"|   | 重複數量 | {duplicate_count} |\n"
    markdown_table += f"|   | 失敗數量 | {failed_count} |\n"

    print('處理摘要:')
    print(f'  總共文件: {total_files}')
    print(f'  成功處理: {success_count}')
    print(f'  重複檔案: {duplicate_count}')
    print(f'  失敗檔案: {failed_count}')

    with open(os.path.join(output_directory, 'output.md'), 'w', encoding='utf-8') as f:
        f.write(markdown_table)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='處理 QR code 發票，支援 JPG/JPEG/PNG/PDF 檔案。'
    )
    parser.add_argument(
        'input_dir',
        nargs='?',
        default='./input/',
        help='輸入資料夾路徑（預設 ./input/）'
    )
    parser.add_argument(
        'output_dir',
        nargs='?',
        default='./output/',
        help='輸出資料夾路徑（預設 ./output/）'
    )
    args = parser.parse_args()

    process_invoice_directory(args.input_dir, args.output_dir)