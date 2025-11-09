# test_ocr_output.py
"""
A local script to test the full parsing pipeline on a single PDF.
This runs *outside* of Docker and Celery.

Usage:
  1. Make sure you have all requirements installed in your local venv:
     pip install -r requirements.txt
  2. Run this script from your project root:
     python test_ocr_output.py "path/to/your/pdf.pdf"
"""

import sys
import logging
from app.parsing.main_parser import ParserOrchestrator
from app.config import settings

# Configure basic logging to see output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Mock Settings for local running ---
# This is a bit of a hack, but it allows the parser to run
# without the full FastAPI/Celery environment.
# We manually set the TESSERACT_OCR_ENABLED flag.
class MockSettings:
    TESSERACT_OCR_ENABLED = True
    TESSERACT_PATH = None # Set to your Tesseract path if needed
    OCR_LANGUAGE = "eng"

# Monkey-patch the settings object for the orchestrator
from app.parsing import main_parser
main_parser.settings = MockSettings()

# Also patch the settings for the base parser
from app.parsing.strategies import amex_parser
amex_parser.settings = MockSettings()
# (Add patches for other parsers if you test them)
# --- End of Mock ---


if len(sys.argv) < 2:
    print("Usage: python test_ocr_output.py \"<path/to/your/pdf.pdf>\"")
    sys.exit(1)

pdf_path = sys.argv[1]

try:
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
except FileNotFoundError:
    print(f"Error: File not found at {pdf_path}")
    sys.exit(1)
except Exception as e:
    print(f"Error reading file: {e}")
    sys.exit(1)


print(f"Testing parser with PDF: {pdf_path}")
orchestrator = ParserOrchestrator(pdf_bytes)

# 1. Test Text Extraction (with OCR fallback)
try:
    orchestrator._extract_text()
    print("=" * 80)
    print("EXTRACTED TEXT (first 1000 characters):")
    print("=" * 80)
    print(orchestrator.full_text[:1000])
    print("=" * 80)
    print(f"\nTotal length: {len(orchestrator.full_text)} characters")
    print("=" * 80)
except Exception as e:
    print(f"\n--- ERROR during text extraction ---\n{e}")
    sys.exit(1)

# 2. Test Provider Identification and Parsing
try:
    orchestrator._identify_provider()
    print(f"\nProvider Identified: {orchestrator.provider_name}")
    
    # Try parsing
    data = orchestrator.parser_strategy.parse()
    print("\n--- EXTRACTED DATA ---")
    print(f"  Statement End Date: {data.statement_end_date}")
    print(f"  Payment Due Date: {data.payment_due_date}")
    print(f"  Total Balance: {data.total_balance}")
    print(f"  Min Payment: {data.min_payment_due}")
    print(f"  Card Digits: {data.card_last_4_digits}")
    print(f"\nMetadata: {data.metadata}")
    print("=" * 80)
    print("\nTest completed successfully.")

except Exception as e:
    print(f"\n--- ERROR during parsing ---\n{e}")
    sys.exit(1)