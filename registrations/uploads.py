"""Checking what candidates upload, before anything is stored.

Official papers — birth certificate, ID card, medical certificate — must be
scans. "Scanned" is read from the file itself: a scanner or a phone's scanning
app produces a PDF whose every page carries a picture of the paper, while a
document exported from a word processor is vector text with, at most, a small
logo. A page counts as scanned when one image on it is big enough to cover a
good part of the page at a modest resolution. A scan that was also run through
OCR keeps its image and passes; it only fails if there is no picture at all.

Only the image dictionaries are read — width and height — never the pixels,
so checking a file costs next to nothing.
"""

import io
import os

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PAGES = 20

# A page is scanned when its largest image would cover at least this share of
# the page at this resolution: 40 % of an A4 page at 100 dpi is about 390,000
# pixels. A phone scan at 150 dpi is about 2 million.
SCAN_DPI = 100
SCAN_MIN_SHARE = 0.4

MIN_PHOTO_SIDE = 200


class UploadProblem(Exception):
    """Why a file was refused, as a code the form can translate."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self):
        return {'code': self.code, 'message': self.message}


def _read(uploaded) -> bytes:
    """The file's bytes, leaving it rewound for whoever saves it next."""
    uploaded.seek(0)
    data = uploaded.read()
    uploaded.seek(0)
    return data


def _largest_image_pixels(xobjects, depth=0) -> int:
    """Pixel count of the biggest image among these XObjects.

    Some scanners wrap the page image in a Form XObject, so forms are looked
    into as well — a few levels deep, never forever.
    """
    if not xobjects or depth > 3:
        return 0
    largest = 0
    for name in xobjects:
        try:
            obj = xobjects[name].get_object()
            subtype = obj.get('/Subtype')
            if subtype == '/Image':
                largest = max(largest, int(obj.get('/Width', 0)) * int(obj.get('/Height', 0)))
            elif subtype == '/Form':
                resources = obj.get('/Resources')
                if resources is not None:
                    inner = resources.get_object().get('/XObject')
                    if inner is not None:
                        largest = max(largest, _largest_image_pixels(inner.get_object(), depth + 1))
        except Exception:  # noqa: BLE001 - a malformed object just contributes nothing
            continue
    return largest


def _page_is_scanned(page) -> bool:
    try:
        width_in = float(page.mediabox.width) / 72
        height_in = float(page.mediabox.height) / 72
    except Exception:  # noqa: BLE001
        width_in, height_in = 8.27, 11.69          # assume A4
    needed = width_in * SCAN_DPI * height_in * SCAN_DPI * SCAN_MIN_SHARE

    resources = page.get('/Resources')
    if resources is None:
        return False
    xobjects = resources.get_object().get('/XObject')
    if xobjects is None:
        return False
    return _largest_image_pixels(xobjects.get_object()) >= needed


def check_scanned_pdf(uploaded) -> None:
    name = (getattr(uploaded, 'name', '') or '').lower()
    if getattr(uploaded, 'size', 0) > MAX_PDF_BYTES:
        raise UploadProblem('TOO_LARGE', 'A PDF must be 10 MB or smaller.')

    data = _read(uploaded)
    if not data:
        raise UploadProblem('EMPTY', 'The file is empty.')
    # The extension proves nothing; the first bytes do.
    if not name.endswith('.pdf') or not data.lstrip()[:5] == b'%PDF-':
        raise UploadProblem('NOT_PDF', 'Only PDF files are accepted for this document.')

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UploadProblem('ENCRYPTED', 'The PDF is password-protected.')
        pages = list(reader.pages)
    except UploadProblem:
        raise
    except Exception:  # noqa: BLE001 - anything pypdf cannot open is damaged to us
        raise UploadProblem('DAMAGED', 'The PDF could not be read.')

    if not pages:
        raise UploadProblem('DAMAGED', 'The PDF has no pages.')
    if len(pages) > MAX_PAGES:
        raise UploadProblem('TOO_MANY_PAGES', f'A PDF may have at most {MAX_PAGES} pages.')
    if not all(_page_is_scanned(page) for page in pages):
        raise UploadProblem(
            'NOT_SCANNED',
            'This PDF is not a scan. Scan the paper document with a scanner or a '
            'scanning app and upload that PDF.')


def check_image(uploaded) -> None:
    name = (getattr(uploaded, 'name', '') or '').lower()
    if getattr(uploaded, 'size', 0) > MAX_IMAGE_BYTES:
        raise UploadProblem('TOO_LARGE', 'An image must be 5 MB or smaller.')
    if os.path.splitext(name)[1] not in ('.jpg', '.jpeg', '.png'):
        raise UploadProblem('NOT_IMAGE', 'Only JPG or PNG images are accepted for this document.')

    data = _read(uploaded)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            kind, size = image.format, image.size
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise UploadProblem('NOT_IMAGE', 'The image could not be read.')
    if kind not in ('JPEG', 'PNG'):
        raise UploadProblem('NOT_IMAGE', 'Only JPG or PNG images are accepted for this document.')
    if min(size) < MIN_PHOTO_SIDE:
        raise UploadProblem('TOO_SMALL', f'The image must be at least {MIN_PHOTO_SIDE} pixels on each side.')


def check_upload(uploaded, file_kind: str) -> None:
    """Raise UploadProblem unless the file suits the document it was sent for."""
    from .models import RequiredDocument

    if file_kind == RequiredDocument.IMAGE:
        check_image(uploaded)
    else:
        check_scanned_pdf(uploaded)
