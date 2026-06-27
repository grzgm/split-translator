"""Builds tiny EPUB and PDF files at test time (no committed binaries)."""

import zipfile
from pathlib import Path

import pymupdf

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
    <dc:identifier id="id">test-1</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>"""

_CH1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ch1</title></head>
<body><h1>Chapter One</h1><p>The first paragraph.</p></body></html>"""

_CH2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ch2</title></head>
<body><h1>Chapter Two</h1><p>The second paragraph.</p></body></html>"""


def make_epub(dir_path) -> str:
    path = Path(dir_path) / "book.epub"
    with zipfile.ZipFile(path, "w") as z:
        # The mimetype entry must be first and stored (uncompressed) per the spec.
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _OPF)
        z.writestr("OEBPS/ch1.xhtml", _CH1)
        z.writestr("OEBPS/ch2.xhtml", _CH2)
    return str(path)


def make_pdf(dir_path) -> str:
    path = Path(dir_path) / "book.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One")
    page.insert_text((72, 110), "The first paragraph.")
    doc.save(str(path))
    doc.close()
    return str(path)
