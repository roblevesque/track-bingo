"""Reading a playlist sheet (pasted from Excel, a CSV, or an .xlsx) into rows of text, and writing the
blank template. Standard library only: an .xlsx file is a zip of XML, so no Excel package is needed.

Everything returns plain lists of strings; deciding which column is the artist and which the song is done in
app/services/planner.py.
"""

from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

MAX_ROWS = 500
MAX_COLUMNS = 8
MAX_CELL = 200
MAX_UPLOAD_BYTES = 2_000_000
MAX_UNZIPPED_BYTES = 20_000_000
TEMPLATE_HEADER = ("Artist", "Song")
TEMPLATE_EXAMPLES = (("ABBA", "Dancing Queen"), ("Queen", "Killer Queen"), ("Prince", ""))


class SheetError(ValueError):
    """Something a person can fix, worded for them."""


def clean_rows(rows: list[list[object]]) -> list[list[str]]:
    """Tidy cells (one line, trimmed, not too long), drop empty rows, cap the size, square the table off."""
    out: list[list[str]] = []
    for row in rows:
        cells = ["" if c is None else " ".join(str(c).split())[:MAX_CELL] for c in row][:MAX_COLUMNS]
        if any(cells):
            out.append(cells)
        if len(out) > MAX_ROWS:
            raise SheetError(f"That sheet has more than {MAX_ROWS} rows. Split it into smaller playlists.")
    width = max((len(r) for r in out), default=0)
    while width and not any(r[width - 1] if len(r) >= width else "" for r in out):
        width -= 1  # trailing columns that are empty everywhere
    return [r + [""] * (width - len(r)) if len(r) < width else r[:width] for r in out]


# ---------------------------------------------------------------- reading

def rows_from_text(text: str) -> list[list[str]]:
    """Cells pasted from Excel are separated by tabs; a pasted CSV by commas; a plain list is one column."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if any("\t" in line for line in lines):
        return clean_rows([line.split("\t") for line in lines])
    if sum("," in line for line in lines) >= max(1, len(lines) // 2):
        return clean_rows(list(csv.reader(lines)))
    return clean_rows([[line] for line in lines])


def rows_from_csv(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # what older Excel writes
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return clean_rows(list(csv.reader(io.StringIO(text), dialect)))


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _column_index(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref)
    n = 0
    for ch in (letters.group(0).upper() if letters else "A"):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(t.text or "" for t in element.iter("{%s}t" % _NS["m"]))


def rows_from_xlsx(data: bytes) -> list[list[str]]:
    """The first sheet of an .xlsx file, as the text a person sees in each cell."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SheetError("That doesn't look like an Excel (.xlsx) file.") from None
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNZIPPED_BYTES:
            raise SheetError("That Excel file is too big to read.")
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise SheetError("That doesn't look like an Excel (.xlsx) file.")
        try:
            sheet_path = "xl/worksheets/sheet1.xml"
            if "xl/_rels/workbook.xml.rels" in names:
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                first = workbook.find("m:sheets/m:sheet", _NS)
                rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                if first is not None:
                    for rel in rels:
                        if rel.get("Id") == first.get(_REL):
                            target = rel.get("Target", "")
                            sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            if sheet_path not in names:
                raise SheetError("Couldn't find the first sheet in that Excel file.")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                for si in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                    shared.append(_text_of(si))
            sheet = ET.fromstring(archive.read(sheet_path))
        except ET.ParseError:
            raise SheetError("That Excel file is damaged or in a format I can't read.") from None

    rows: list[list[object]] = []
    for row in sheet.iterfind("m:sheetData/m:row", _NS):
        index = int(row.get("r", len(rows) + 1)) - 1
        if index > MAX_ROWS * 4:
            break
        while len(rows) <= index:
            rows.append([])
        cells: list[object] = rows[index]
        for cell in row.findall("m:c", _NS):
            col = _column_index(cell.get("r", "A1"))
            if col >= MAX_COLUMNS * 4:
                continue
            kind, value = cell.get("t", "n"), cell.find("m:v", _NS)
            if kind == "s" and value is not None and value.text and value.text.isdigit() and int(value.text) < len(shared):
                text = shared[int(value.text)]
            elif kind == "inlineStr":
                text = _text_of(cell.find("m:is", _NS))
            else:
                text = value.text if value is not None and value.text else ""
            while len(cells) <= col:
                cells.append("")
            cells[col] = text
    return clean_rows(rows)


def rows_from_upload(filename: str, data: bytes) -> list[list[str]]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise SheetError("That file is too big. A playlist sheet should be a few kilobytes.")
    name = filename.lower()
    if name.endswith(".xlsx"):
        return rows_from_xlsx(data)
    if name.endswith((".csv", ".txt", ".tsv")):
        return rows_from_text(data.decode("utf-8-sig", errors="replace")) if name.endswith((".txt", ".tsv")) else rows_from_csv(data)
    if name.endswith(".xls"):
        raise SheetError("Old .xls files can't be read. In Excel use Save As and choose .xlsx or CSV.")
    raise SheetError("Upload an Excel (.xlsx) or CSV file, or paste the cells instead.")


# ---------------------------------------------------------------- the template

def template_csv() -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADER)
    writer.writerows(TEMPLATE_EXAMPLES)
    return "﻿" + out.getvalue()  # the byte-order mark makes Excel read accents correctly


def template_xlsx() -> bytes:
    """A minimal workbook with an Artist and a Song column and a few example rows."""
    def cell(ref: str, text: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(text)}</t></is></c>' if text else ""

    rows = [TEMPLATE_HEADER, *TEMPLATE_EXAMPLES]
    body = "".join(
        f'<row r="{i}">{cell(f"A{i}", a)}{cell(f"B{i}", b)}</row>' for i, (a, b) in enumerate(rows, start=1)
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<cols><col min="1" max="2" width="32" customWidth="1"/></cols>'
        f"<sheetData>{body}</sheetData></worksheet>"
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Playlist" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": sheet,
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return out.getvalue()
