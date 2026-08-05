from __future__ import annotations

import numpy as np
import fitz
import cv2


def pdf_bytes_to_image(pdf_bytes: bytes, page_number: int = 0, dpi: int = 200) -> np.ndarray:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if page_number >= doc.page_count:
        raise ValueError(
            f"PDF only has {doc.page_count} pages, page {page_number} requested"
        )

    page = doc.load_page(page_number)

    zoom = dpi / 72  # need uniform scalling
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n)

    if pix.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    elif pix.n == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    doc.close()
    return img


def pdf_page_count(pdf_bytes: bytes) -> int:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    count = doc.page_count
    doc.close()
    return count
