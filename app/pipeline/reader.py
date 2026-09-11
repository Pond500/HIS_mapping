"""
reader.py
=========
File bytes -> sheets of raw cells. No interpretation here.
CSV: encoding and delimiter are detected. XLSX via openpyxl, XLS via xlrd.
"""

import csv
import io
from dataclasses import dataclass
from datetime import datetime

import openpyxl
from openpyxl.utils import get_column_letter

ENCODINGS = ["utf-8-sig", "utf-8", "cp874", "utf-16"]


@dataclass
class Sheet:
    name: str
    rows: list[list]          # raw cell values, ragged rows padded to equal width

    def cell_ref(self, r: int, c: int) -> str:
        return f"{get_column_letter(c + 1)}{r + 1}"


def _pad(rows):
    # drop trailing empty rows/columns, pad to a rectangle
    rows = [list(r) for r in rows]
    while rows and all(v in (None, "") for v in rows[-1]):
        rows.pop()
    width = max((len(r) for r in rows), default=0)
    while width and all(len(r) < width or r[width - 1] in (None, "") for r in rows):
        width -= 1
    return [(r + [None] * width)[:width] for r in rows]


def _decode(data: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("อ่าน encoding ของไฟล์ CSV ไม่ได้")


def read_csv(data: bytes, name="csv") -> list[Sheet]:
    text = _decode(data)
    sample = "\n".join(text.splitlines()[:30])
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delim = max(",;\t|", key=sample.count)
    rows = [[(v if v.strip() != "" else None) for v in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    return [Sheet(name, _pad(rows))]


def read_xlsx(data: bytes) -> list[Sheet]:
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        rows = _pad(ws.iter_rows(values_only=True))
        if rows:
            out.append(Sheet(ws.title, rows))
    wb.close()
    return out


def read_xls(data: bytes) -> list[Sheet]:
    import xlrd
    book = xlrd.open_workbook(file_contents=data)
    out = []
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(datetime(*xlrd.xldate_as_tuple(cell.value, book.datemode)))
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                else:
                    row.append(cell.value)
            rows.append(row)
        rows = _pad(rows)
        if rows:
            out.append(Sheet(sh.name, rows))
    return out


def read_file(data: bytes, ext: str) -> list[Sheet]:
    ext = ext.lower().lstrip(".")
    if ext == "csv":
        return read_csv(data)
    if ext == "xlsx":
        return read_xlsx(data)
    if ext == "xls":
        return read_xls(data)
    raise ValueError(f"ไม่รองรับไฟล์ .{ext}")
