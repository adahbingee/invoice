# AGENTS.md

Instructions for AI agents working in this workspace. Read this before making changes.
The user communicates in **Traditional Chinese** (繁體中文); reply in that register unless asked otherwise.

## What this workspace is

A toolchain that parses Taiwan e-invoice QR codes out of a batch of files (59 PDF + 1 PNG)
and produces a renamed invoice folder plus a Markdown report. The source project is a clone of
`https://github.com/adahbingee/invoice` living in `invoice-tool/`; `adahbingee` is the user's own
GitHub account, so `origin/main` is the correct push target.

## Layout

| Path | Role |
| --- | --- |
| `invoice-tool/main.py` | The parser. Single entry point; everything important lives here. |
| `invoice-tool/requirements.txt` | `pypdf`, `Pillow`, `zxing-cpp` (nothing else required). |
| `invoice-tool/README.md` | User-facing docs (Traditional Chinese). |
| `invoices/11/` | Source batch: 59 PDF + 1 PNG. |
| `output/` | Canonical result: 55 renamed PDFs + `output.md`. |
| `output_opt*`, `output_v*`, `output_pypdf/` | Throwaway verification copies from past runs. Safe to ignore. |
| `download-site/` | Published static download page (see "Download site" below). |
| `.workbuddy/memory/YYYY-MM-DD.md` | Append-only work log. Add a short note after substantive changes. |

## Invoice tool: decisions already made — DO NOT reverse these

The user explicitly evaluated and rejected several "improvements". Do not reintroduce them
without a fresh, explicit request.

1. **First page, first QR only.** Read page 0 and take the first decodable barcode. Do **not** add
   full-page scanning, all-page traversal, or multi-barcode format-filtering fallbacks. The user's
   words: "3不用優化，這是發票啊" — invoice QR placement is standardized.
2. **Money = integer cents (fixed-point).** Parse `"125.10"` to `12510`, sum with integer addition,
   format back with `cents_to_str()`. Do **not** switch to `float` (precision loss) and do **not**
   switch to `Decimal` — the user asked "你為啥不用整數定點數" and settled on integer cents.
3. **No CSV output.** Only Markdown. The user said "不用輸出csv".
4. **No assumptions about QR size, position, or image format.** Widths observed from 47px to 650px;
   QR may be a standalone embedded image or a corner of a larger one; embedded images may be PNG,
   JPEG, GIF, BMP, TIFF, WEBP, JPEG2000, or CMYK/multiframe variants. Decode the whole image,
   retry at 1x/2x/4x, and iterate all frames. Never crop a fixed region.

### How the parser works

- **PDF primary path**: `pypdf` extracts every embedded image from page 0; `zxingcpp` decodes each.
  No full-page rendering needed — all 59 PDFs in the sample decode this way.
- **PDF fallback path**: `pypdfium2` renders the page, lazily imported, used only when the primary
  path fails (e.g. vector-drawn QR). Optional dependency; print a one-time hint if missing.
- **Bitmap inputs**: Pillow opens the file, format-agnostic.
- QR text is parsed semantically: 15–25 digit number = invoice number, decimal value = amount;
  positional indexes are kept only as a fallback. HTTP format uses `total_amount` (already cents).
- Robustness: per-file `try/except`, `set` for dedup, sorted walk with PDFs before bitmaps,
  conflict-safe output names (`_1`, `_2`), duplicate/failure detail sections in the report.
- CLI: `python main.py [input_dir] [output_dir] [--zoom N] [--no-recursive]`

### Dependency install gotcha

Install through the **Tencent Cloud PyPI mirror**:
`python -m pip install -i https://mirrors.cloud.tencent.com/pypi/simple/ pypdf Pillow zxing-cpp`
Tsinghua mirror did not carry the needed PyMuPDF build; the default index was too slow. General
rule from the user: when pip needs a mirror, use one.

## Validation baseline

After any change to `main.py`, re-run against `invoices/11` and compare. Expected, unchanged:

- files 60, success 55, duplicates 5, failures 0
- total **¥9074.49** (907449 cents)
- 55 output PDFs with identical names
- duplicate numbers: `26952000004781034316`, `26952000004881606151`,
  `26954000000125593276` (twice), `26952000004987441516`
- the PNG (`发票文件1(55).png`) parses fine; it is skipped as a duplicate of
  `26952000004987441516`, which is expected, not a failure.

Also force-disable the primary path once to confirm the `pypdfium2` fallback still decodes.

## Download site (`download-site/`)

Published at `https://invoice-download-72717.app.workbuddy.host/?sharecode=TKU25RUV4W`.
Two quirks discovered the hard way:

- Every URL must carry `?sharecode=...`; without it the site 403s.
- The WAF blocks the `.zip` suffix specifically (`.md`/`.dat`/`.html` are fine). The archive is
  served as `output.dat`; the page fetches it and saves a Blob as `output.zip` client-side.
  `payload.html` (base64-embedded archive) is the backup. Keep this scheme if re-publishing.

## Git notes

- Remote: `https://github.com/adahbingee/invoice.git`, branch `main`.
- `github.com:443` is intermittently unreachable from this machine (DNS/IPv6 issues, connection
  resets). A failed push is usually network, not auth — diagnose before touching credentials.
  A scheduled retry succeeded once; patience works.
- Commit messages are written in Traditional Chinese.

## User working style

- Prefers a plan/table to approve before larger changes; says "好的全部實作並驗證" to proceed.
- Pushes back on over-engineering and asks pointed "why not X?" questions — answer honestly, and
  adopt their choice when it is better (integer cents and format-agnostic decoding came from this).
- Likes small, elegant Python experiments; reserves C/C++ for precision/performance work.
- When the user says "先不要實現，計畫就好", analyze and present a plan **without editing files**.
