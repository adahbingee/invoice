import os
import re
import shutil
import zxingcpp
import fitz
from PIL import Image


def pdf_to_image(pdf_path, page_num=0):
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_num)
    zoom = 2
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img


def crop_image(image, area):
    return image.crop(area)


def decode_qrcode(image):
    results = zxingcpp.read_barcodes(image)
    if results:
        return results[0].text
    return None


def process_ticket(image: Image):
    width, height = image.size
    top_left_area = (0, 0, width * 0.4, height * 0.4)
    top_left_image = crop_image(image, top_left_area)

    qr_code_data = decode_qrcode(top_left_image)
    if qr_code_data:
        if qr_code_data.startswith("http"):
            amount_re = re.compile(r'total_amount=(\d+)')
            amount_match = amount_re.search(qr_code_data)
            if amount_match:
                amount = int(amount_match.group(1)) / 100
            else:
                amount = "Not found"

            invoice_number_re = re.compile(r'bill_num=(\d+)')
            invoice_number_match = invoice_number_re.search(qr_code_data)
            if invoice_number_match:
                invoice_number = invoice_number_match.group(1)
            else:
                invoice_number = "Not found"
        else:
            split_data = qr_code_data.split(',')
            if len(split_data) > 4:
                try:
                    amount = float(split_data[4])
                except ValueError:
                    amount = "Not found"
            else:
                amount = "Not found"

            if len(split_data) > 3:
                invoice_number = split_data[3]
            else:
                invoice_number = "Not found"
    else:
        amount = "Not found"
        invoice_number = "Not found"

    return amount, invoice_number


def process_img(img_file):
    image = Image.open(img_file)
    amount, invoice_number = process_ticket(image)
    return os.path.basename(img_file), amount, invoice_number


def process_pdf(pdf_file):
    image = pdf_to_image(pdf_file, 0)
    amount, invoice_number = process_ticket(image)
    return os.path.basename(pdf_file), amount, invoice_number


def process_invoice_directory(directory_path, output_directory):
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    markdown_table = "| 流水號 | 發票號碼 | 金額 |\n| --- | --- | ---: |\n"
    serial_number = 1
    total_amount = 0
    invoice_numbers = []

    for file in os.listdir(directory_path):
        if file.endswith('.jpg'):
            img_path = os.path.join(directory_path, file)
            print(f"處理文件：{img_path}")
            file_name, amount, invoice_number = process_img(img_path)

            if invoice_number in invoice_numbers:
                print(f'跳過重複發票 {invoice_number}\n')
                continue

            new_file_name = f"{invoice_number}_{amount:.2f}.jpg"
            new_file_path = os.path.join(output_directory, new_file_name)
            shutil.copyfile(img_path, new_file_path)

            markdown_table += f"| {serial_number} | {invoice_number} | {amount:.2f} |\n"
            serial_number += 1
            total_amount += amount
            invoice_numbers.append(invoice_number)

            print(f"新文件名稱: {new_file_name}")
            print('-------------------')

        if file.endswith('.pdf'):
            pdf_path = os.path.join(directory_path, file)
            print(f"處理文件：{pdf_path}")
            file_name, amount, invoice_number = process_pdf(pdf_path)

            if invoice_number in invoice_numbers:
                print(f'跳過重複發票 {invoice_number}\n')
                continue

            new_file_name = f"{invoice_number}_{amount:.2f}.pdf"
            new_file_path = os.path.join(output_directory, new_file_name)
            shutil.copyfile(pdf_path, new_file_path)

            markdown_table += f"| {serial_number} | {invoice_number} | {amount:.2f} |\n"
            serial_number += 1
            total_amount += amount
            invoice_numbers.append(invoice_number)

            print(f"新文件名稱: {new_file_name}")
            print('-------------------')

    total_amount = round(total_amount, 2)
    markdown_table += f"|   | 合計金額 | {total_amount} |\n"

    with open(os.path.join(output_directory, 'output.md'), 'w', encoding='utf-8') as f:
        f.write(markdown_table)


if __name__ == '__main__':
    directory_path   = './input/'
    output_directory = './output/'
    process_invoice_directory(directory_path, output_directory)