# app/parsing/strategies/amex_parser.py

import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime, date

from app.parsing.strategies.base_parser import BaseParser
from app.schemas import ExtractedData

logger = logging.getLogger(__name__)


class AmexParser(BaseParser):
    """
    Advanced American Express statement parser.
    
    Features:
    - Multi-strategy extraction (regex → keyword proximity → table)
    - Confidence scoring and validation
    - Robust error handling and logging
    - Support for multiple date and amount formats
    """
    
    PROVIDER_NAME = "Amex"
    
    # Field configurations with multiple patterns and keywords
    FIELD_CONFIG = {
        "statement_end_date": {
            "patterns": [
                # More flexible patterns for OCR
                r"Closing\s*Date[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4})",
                r"Statement\s*(?:Closing\s*)?Date[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4})",
                r"Statement\s*End(?:ing)?[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4})",
                # Add numeric formats
                r"Closing\s*Date[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})",
            ],
            "keywords": ["closing date", "statement closing date", "statement end date", "statement date"],
            "table_keys": ["Closing Date", "Statement Date"]
        },
        "payment_due_date": {
            "patterns": [
                # This one worked! Keep similar flexible patterns
                r"Payment\s*Due\s*Date[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4})",
                r"Due\s*Date[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4})",
                r"Pay(?:ment)?\s*By[:\s]+(\w+\.?\s+\d{1,2},?\s+\d{4})",
                r"Payment\s*Due\s*Date[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})",
            ],
            "keywords": ["payment due date", "due date", "payment due", "pay by"],
            "table_keys": ["Payment Due Date", "Due Date"]
        },
        "total_balance": {
            "patterns": [
                # More flexible amount patterns for OCR
                r"New\s*Balance[:\s]+\$?\s*([\d,]+\.?\d{2})",
                r"Total\s*Balance[:\s]+\$?\s*([\d,]+\.?\d{2})",
                r"Balance\s*Due[:\s]+\$?\s*([\d,]+\.?\d{2})",
                r"Current\s*Balance[:\s]+\$?\s*([\d,]+\.?\d{2})",
                # Handle cases where $ is on next line
                r"New\s*Balance[:\s]+.*?\$\s*([\d,]+\.\d{2})",
            ],
            "keywords": ["new balance", "total balance", "balance due", "current balance", "amount due"],
            "table_keys": ["New Balance", "Total Balance", "Balance Due"]
        },
        "min_payment_due": {
            "patterns": [
                r"Minimum\s*Payment\s*Due[:\s]+\$?\s*([\d,]+\.?\d{2})",
                r"Minimum\s*(?:Amount\s*)?Due[:\s]+\$?\s*([\d,]+\.?\d{2})",
                r"Min(?:imum)?\s*Payment[:\s]+\$?\s*([\d,]+\.?\d{2})",
                r"Minimum\s*Payment[:\s]+.*?\$\s*([\d,]+\.\d{2})",
                # Handle format "Minimum Amount Due S 19.00"
                r"Minimum\s*Amount\s*Due\s*S\s*([\d,]+\.?\d{2})"
            ],
            "keywords": ["minimum payment due", "minimum payment", "minimum amount due", "min payment"],
            "table_keys": ["Minimum Payment Due", "Minimum Payment", "Min Payment"]
        },
        "card_last_4_digits": {
            "patterns": [
                # More flexible card patterns
                r"Account\s*Ending\s*[:\-]?\s*(\d{4,5})",
                r"Account\s*(?:Number\s*)?Ending\s*[:\-]?\s*(\d{4,5})",
                r"Card\s*Ending\s*[:\-]?\s*(\d{4,5})",
                # Handle "3750-123456-78900" format
                r"\d{4,6}[\s\-]\d{6}[\s\-](\d{5})",
                r"[x×X*]{4,}[\s\-]?(\d{4})",  # Masked formats
            ],
            "keywords": ["account ending", "card ending", "account number", "card number"],
            "table_keys": ["Account Ending", "Card Number"]
        }
    }


    def parse(self) -> ExtractedData:
        """
        Orchestrates multi-strategy parsing with confidence scoring.
        """
        
        results = {}
        confidence_scores = {}
        
        for field_name, config in self.FIELD_CONFIG.items():
            value, confidence = self._extract_field(field_name, config)
            results[field_name] = value
            confidence_scores[field_name] = confidence
            
            if value:
                logger.info(f"Extracted {field_name}: {value} (confidence: {confidence:.2f})")
            else:
                logger.warning(f"Failed to extract {field_name}")
        
        # Populate ExtractedData schema
        self.extracted_data.statement_end_date = self._parse_date(results.get("statement_end_date"))
        self.extracted_data.payment_due_date = self._parse_date(results.get("payment_due_date"))
        self.extracted_data.total_balance = self._clean_amount(results.get("total_balance"))
        self.extracted_data.min_payment_due = self._clean_amount(results.get("min_payment_due"))
        self.extracted_data.card_last_4_digits = self._normalize_card_digits(results.get("card_last_4_digits"))
        
        # Store confidence scores for downstream validation
        self.extracted_data.metadata = {
            "provider": self.PROVIDER_NAME,
            "confidence_scores": confidence_scores,
            "extraction_method": "hybrid_multi_strategy"
        }
        
        # Validate extracted data
        self._validate_extracted_data()
        
        return self.extracted_data


    def _extract_field(self, field_name: str, config: Dict[str, Any]) -> tuple[Optional[str], float]:
        """
        Multi-strategy field extraction with confidence scoring.
        
        Returns:
            Tuple of (extracted_value, confidence_score)
        """
        
        # Strategy 1: Regex patterns (confidence: 0.95)
        for pattern in config.get("patterns", []):
            value = self._find_by_regex(pattern, self.text)
            if value:
                return value, 0.95
        
        # Strategy 2: Keyword proximity search (confidence: 0.85)
        for keyword in config.get("keywords", []):
            if "date" in field_name:
                value = self._find_date_near_keyword(keyword)
            elif "balance" in field_name or "payment" in field_name:
                value = self._find_amounts_near_keyword(keyword)
            elif "card" in field_name or "digits" in field_name:
                value = self._find_last4_card()
            else:
                value = self._find_text_near_keyword(keyword)
            
            if value:
                return value, 0.85
        
        # Strategy 3: Table extraction fallback (confidence: 0.75)
        table_data = self._extract_table_data()
        if table_data:
            for table_key in config.get("table_keys", []):
                if table_key in table_data:
                    value = table_data[table_key]
                    if value:
                        return value, 0.75
        
        return None, 0.0


    def _normalize_card_digits(self, raw_value: Optional[str]) -> Optional[str]:
        """Normalize card number to last 4 digits."""
        if not raw_value:
            return None
        
        # Extract only digits
        digits = re.sub(r'\D', '', raw_value)
        
        # Return last 4 digits
        return digits[-4:] if len(digits) >= 4 else digits


    def _validate_extracted_data(self) -> None:
        """
        Validates extracted data for logical consistency.
        Logs warnings for suspicious values.
        """
        
        # Date validation
        if self.extracted_data.payment_due_date and self.extracted_data.statement_end_date:
            if self.extracted_data.payment_due_date <= self.extracted_data.statement_end_date:
                logger.warning("Payment due date is before or equal to statement end date")
        
        # Amount validation
        if self.extracted_data.min_payment_due and self.extracted_data.total_balance:
            if self.extracted_data.min_payment_due > self.extracted_data.total_balance:
                logger.warning("Minimum payment exceeds total balance")
        
        # Card digits validation
        if self.extracted_data.card_last_4_digits:
            if not re.match(r'^\d{4}$', self.extracted_data.card_last_4_digits):
                logger.warning(f"Card digits not in expected format: {self.extracted_data.card_last_4_digits}")