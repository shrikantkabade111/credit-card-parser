# app/parsing/ocr_utils.py
"""
OCR helper that performs lightweight image enhancement on pdf2image PIL images
before passing them to pytesseract. Designed to increase OCR yield for scanned
statements without pulling in OpenCV.

Uses:
- pdf2image (convert_from_bytes) -> returns PIL Images
- Pillow (PIL.Image, ImageOps, ImageFilter, ImageEnhance)
- pytesseract.image_to_string

This module intentionally avoids heavy native deps (like cv2) so it's easier to
run inside Docker images that already include tesseract & poppler.
"""

from io import BytesIO
from typing import List, Optional
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
from pdf2image import convert_from_bytes
import pytesseract
import logging

logger = logging.getLogger(__name__)


def _preprocess_pil_image(img: Image.Image, upscale: bool = True) -> Image.Image:
    """
    Apply enhancement to a PIL image to improve OCR quality.
    Steps:
    - Convert to grayscale
    - Auto-contrast
    - Slight sharpening via unsharp mask (via PIL filters)
    - Optional upscale (improves OCR on low-DPI scans)
    - Binarize using a dynamic threshold approximation
    """
    # convert to L (grayscale)
    img_l = img.convert("L")

    # optionally upscale (keeps aspect ratio)
    if upscale:
        w, h = img_l.size
        target_dpi = 300
        # naive upscale heuristic: if width < 1000, upscale by 2
        if w < 1200:
            img_l = img_l.resize((int(w * 1.6), int(h * 1.6)), Image.LANCZOS)

    # enhance contrast
    img_l = ImageOps.autocontrast(img_l, cutoff=0)

    # apply median filter to remove speckle noise
    img_l = img_l.filter(ImageFilter.MedianFilter(size=3))

    # slight sharpening using UnsharpMask via ImageFilter.SHARPEN + enhance
    try:
        img_l = img_l.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
    except Exception:
        # fallback to SHARPEN if UnsharpMask not available
        img_l = img_l.filter(ImageFilter.SHARPEN)

    # Binarize using a simple threshold computed from histogram
    hist = img_l.histogram()
    # compute approximate global threshold: mean of histogram weighted by pixel value
    total = sum(hist)
    if total:
        mean = sum(i * hist[i] for i in range(256)) / total
        thresh = int(mean * 0.85)
    else:
        thresh = 128
    img_bin = img_l.point(lambda p: 255 if p > thresh else 0, mode="1")

    # Convert back to L for tesseract (tesseract handles '1' but 'L' is safe)
    img_final = img_bin.convert("L")

    return img_final


def enhanced_ocr_from_bytes(pdf_bytes: bytes, max_pages: Optional[int] = 3,
                            tesseract_lang: str = "eng", tesseract_config: str = "--psm 6") -> str:
    """
    Convert PDF bytes to images and run enhanced OCR on each page.
    Returns concatenated text for first `max_pages` pages.
    """
    texts: List[str] = []
    try:
        images = convert_from_bytes(pdf_bytes, dpi=300)
    except Exception as e:
        logger.exception("pdf2image.convert_from_bytes failed: %s", e)
        return ""

    for i, img in enumerate(images):
        if max_pages and i >= max_pages:
            break
        try:
            logger.debug("OCR preprocessing page %d (size=%s)", i + 1, img.size)
            img_pre = _preprocess_pil_image(img, upscale=True)
            # use pytesseract to get text
            txt = pytesseract.image_to_string(img_pre, lang=tesseract_lang, config=tesseract_config)
            texts.append(txt or "")
        except Exception as e:
            logger.exception("OCR failed on page %d: %s", i + 1, e)
            texts.append("")
    return "\n".join(texts)