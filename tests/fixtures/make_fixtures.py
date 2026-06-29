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


# A 1x1 PNG, the smallest valid image, so a fixture can reference a real file.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f4d0000000049454e44ae42"
    "6082"
)

_IMG_OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Picture Book</dc:title>
    <dc:identifier id="id">test-img</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover" href="Images/cover.png" media-type="image/png"/>
    <item id="pic" href="Images/pic.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>"""

# Chapter lives in OEBPS/Text/, so its ../Images/ refs must resolve to
# OEBPS/Images/ from the EPUB root. Also references a missing image and a
# remote URL, neither of which must be rewritten or collected.
_IMG_CH1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Ch1</title></head>
<body>
<h1>Pictures</h1>
<p><img src="../Images/pic.png" alt="pic"/></p>
<p><img src="../Images/cover.png" alt="cover"/></p>
<p><img src="../Images/missing.png" alt="gone"/></p>
<p><img src="https://example.com/remote.png" alt="remote"/></p>
</body></html>"""


def make_epub_with_images(dir_path) -> str:
    """An EPUB whose chapter sits in a sub-folder and references images via
    ``../Images/...``, exercising root-relative src rewriting and collection."""
    path = Path(dir_path) / "picture-book.epub"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _IMG_OPF)
        z.writestr("OEBPS/Text/ch1.xhtml", _IMG_CH1)
        z.writestr("OEBPS/Images/cover.png", _PNG_1x1)
        z.writestr("OEBPS/Images/pic.png", _PNG_1x1)
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
