# app/parsing/main_parser.py

import pdfplumber
import io
from typing import Optional, Tuple
from app.parsing.strategies.base_parser import BaseParser
from app.parsing.strategies.amex_parser import AmexParser
from app.parsing.strategies.chase_parser import ChaseParser
from app.parsing.strategies.citi_parser import CitiParser
from app.parsing.strategies.cap1_parser import CapitalOneParser
from app.parsing.strategies.boa_parser import BankOfAmericaParser
from app.schemas import ExtractedData
from app.config import settings
import logging

# OCR imports (optional)
try:
    from PIL import Image
    import pytesseract
    import pdf2image
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# Import new OCR helper
try:
    from app.parsing.ocr_utils import enhanced_ocr_from_bytes
    OCR_HELPER_AVAILABLE = True
except Exception:
    OCR_HELPER_AVAILABLE = False

logger = logging.getLogger(__name__)

# Provider detection mapping
PROVIDER_MAP = {
    "american express": AmexParser,
    "amex": AmexParser,
    "chase": ChaseParser,
    "citi": CitiParser,
    "citibank": CitiParser,
    "capital one": CapitalOneParser,
    "bank of america": BankOfAmericaParser,
    "bofa": BankOfAmericaParser,
}


class ParserOrchestrator:
    """
    Orchestrates PDF text extraction, provider identification, and parsing.
    Enhanced with OCR fallback and better error handling.
    """

    def __init__(self, pdf_content: bytes):
        """
        Initialize orchestrator with PDF content.

        Args:
            pdf_content: Raw PDF file bytes
        """
        self.pdf_content = pdf_content
        self.full_text = ""
        self.provider_name: Optional[str] = None
        self.parser_strategy: Optional[BaseParser] = None
        self.task_id: Optional[str] = None

    def _run_ocr_fallback(self) -> None:
        """
        Run Tesseract OCR on scanned/image-based PDFs.
        Uses enhanced pre-processing (ocr_utils.enhanced_ocr_from_bytes) when available.
        Falls back to simpler pytesseract usage if necessary.
        """
        # Respect configuration if present; default to True
        ocr_enabled = getattr(settings, "TESSERACT_OCR_ENABLED", True)
        if not ocr_enabled:
            logger.info(f"[Task {self.task_id}] OCR disabled by configuration")
            return

        if not OCR_AVAILABLE:
            logger.warning(
                f"[Task {self.task_id}] OCR libraries not available. "
                "Install pytesseract and pdf2image for OCR support."
            )
            return

        logger.info(f"[Task {self.task_id}] Running OCR fallback...")

        try:
            # Configure tesseract path if custom
            tesseract_path = getattr(settings, "TESSERACT_PATH", None)
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path

            # prefer enhanced helper if available
            if OCR_HELPER_AVAILABLE:
                lang = getattr(settings, "OCR_LANGUAGE", "eng")
                config = getattr(settings, "OCR_TESSERACT_CONFIG", "--psm 6")
                # Enhanced OCR processes first N pages with preprocessing
                text = enhanced_ocr_from_bytes(self.pdf_content, max_pages=3, tesseract_lang=lang, tesseract_config=config)
                self.full_text = text or ""
                logger.info(f"[Task {self.task_id}] Enhanced OCR completed. Extracted {len(self.full_text)} characters")
                logger.debug(f"[Task {self.task_id}] OCR Text Preview (first 500 chars): {self.full_text[:500]}")
                return

            # Fallback: basic pdf2image + pytesseract (existing behavior)
            images = pdf2image.convert_from_bytes(self.pdf_content, dpi=300, fmt="jpeg")
            all_pages_text = []
            for i, image in enumerate(images):
                logger.debug(f"[Task {self.task_id}] OCR processing page {i+1}/{len(images)}")
                txt = pytesseract.image_to_string(image, lang=getattr(settings, "OCR_LANGUAGE", "eng"),
                                                  config=getattr(settings, "OCR_TESSERACT_CONFIG", "--psm 6"))
                all_pages_text.append(txt)
            self.full_text = "\n".join(all_pages_text)
            logger.info(f"[Task {self.task_id}] OCR completed. Extracted {len(self.full_text)} characters")
            logger.debug(f"[Task {self.task_id}] OCR Text Preview (first 500 chars): {self.full_text[:500]}")

        except Exception as e:
            logger.error(f"[Task {self.task_id}] OCR processing failed: {e}", exc_info=True)
            self.full_text = ""

    def _extract_text(self) -> None:
        """
        Extract text from PDF using pdfplumber with OCR fallback.
        """
        try:
            with io.BytesIO(self.pdf_content) as pdf_file:
                with pdfplumber.open(pdf_file) as pdf:
                    all_pages_text = []
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        all_pages_text.append(page_text)

                    self.full_text = "\n".join(all_pages_text)

            logger.info(
                f"[Task {self.task_id}] Text extraction completed. "
                f"Extracted {len(self.full_text)} characters"
            )

        except Exception as e:
            logger.error(
                f"[Task {self.task_id}] Text extraction failed: {e}",
                exc_info=True
            )
            raise ValueError(
                f"Failed to extract text from PDF. "
                f"File may be corrupted or password-protected."
            )

        # OCR fallback if no text extracted
        if not self.full_text.strip():
            logger.warning(
                f"[Task {self.task_id}] No text extracted. "
                "Attempting OCR fallback..."
            )
            self._run_ocr_fallback()

    def _identify_provider(self) -> None:
        """
        Identify credit card provider from extracted text.
        Uses fuzzy matching on first 3000 characters.
        """
        # Search in first few pages for efficiency
        text_snippet = self.full_text[:3000].lower()

        for keyword, parser_class in PROVIDER_MAP.items():
            if keyword in text_snippet:
                self.provider_name = parser_class.PROVIDER_NAME
                self.parser_strategy = parser_class(self.full_text)
                logger.info(
                    f"[Task {self.task_id}] Provider identified: {self.provider_name}"
                )
                return

        logger.warning(
            f"[Task {self.task_id}] Could not identify provider. "
            f"Text preview: {text_snippet[:200]}..."
        )
        raise ValueError(
            "Could not identify credit card provider. "
            "Supported: Amex, Chase, Citi, Capital One, Bank of America."
        )

    def run_parsing(self, task_id: str = None) -> Tuple[str, ExtractedData]:
        """
        Execute full parsing pipeline.

        Steps:
        1. Extract text (with OCR fallback)
        2. Identify provider
        3. Run provider-specific parser

        Args:
            task_id: Celery task ID for logging

        Returns:
            Tuple of (provider_name, ExtractedData)

        Raises:
            ValueError: If parsing fails
        """
        self.task_id = task_id or "N/A"

        try:
            # Step 1: Extract text
            self._extract_text()

            if not self.full_text.strip():
                raise ValueError(
                    "PDF contains no extractable text. "
                    "File may be empty, image-only, or corrupted."
                )

            # Step 2: Identify provider
            self._identify_provider()

            # Step 3: Parse using provider strategy
            if not self.parser_strategy:
                raise ValueError("Provider identified but no parser strategy set.")

            parsed_data = self.parser_strategy.parse()

            return self.provider_name, parsed_data

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"[Task {self.task_id}] Unexpected parsing error: {e}",
                exc_info=True
            )
            raise ValueError(f"Unexpected parsing error: {str(e)}")