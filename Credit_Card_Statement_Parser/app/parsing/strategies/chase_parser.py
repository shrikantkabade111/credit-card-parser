# app/parsing/strategies/chase_parser.py

import logging
from typing import Optional, Dict, Any
from app.parsing.strategies.base_parser import BaseParser
from app.schemas import ExtractedData

logger = logging.getLogger(__name__)


class ChaseParser(BaseParser):
    """
    Advanced Chase statement parser with multi-strategy extraction.
    """
    
    PROVIDER_NAME = "Chase"
    
    FIELD_CONFIG = {
        "statement_end_date": {
            "patterns": [
                r"Statement Period\s+.*through\s+([\w\s,]+\d{4})",
                r"Closing Date\s+([\w\s,]+\d{4})",
                r"Statement (?:End(?:ing)?|Close)\s+Date[:\s]+([\w\s,]+\d{4})"
            ],
            "keywords": ["statement period through", "closing date", "statement end"],
            "table_keys": ["Closing Date", "Statement End Date"]
        },
        "payment_due_date": {
            "patterns": [
                r"Payment Due Date[:\s]+([\w\s,]+\d{4})",
                r"Due Date[:\s]+([\w\s,]+\d{4})",
                r"Pay(?:ment)? By[:\s]+([\w\s,]+\d{4})"
            ],
            "keywords": ["payment due date", "due date", "payment by"],
            "table_keys": ["Payment Due Date", "Due Date"]
        },
        "total_balance": {
            "patterns": [
                r"New Balance\s+\$([\d,]+\.\d{2})",
                r"Total Balance\s+\$([\d,]+\.\d{2})",
                r"Balance Due\s+\$([\d,]+\.\d{2})",
                r"Current Balance\s+\$([\d,]+\.\d{2})"
            ],
            "keywords": ["new balance", "total balance", "balance due", "current balance"],
            "table_keys": ["New Balance", "Total Balance"]
        },
        "min_payment_due": {
            "patterns": [
                r"Minimum Payment Due\s+\$([\d,]+\.\d{2})",
                r"Minimum Payment\s+\$([\d,]+\.\d{2})",
                r"Min(?:imum)? Pay(?:ment)?\s+\$([\d,]+\.\d{2})"
            ],
            "keywords": ["minimum payment due", "minimum payment", "min payment"],
            "table_keys": ["Minimum Payment Due", "Minimum Payment"]
        },
        "card_last_4_digits": {
            "patterns": [
                r"Account Number[:\s]+.*?(\d{4})",
                r"Card (?:Number|Ending)[:\s]+.*?(\d{4})",
                r"Account Ending[:\s\-]+(\d{4})"
            ],
            "keywords": ["account number", "card ending"],
            "table_keys": ["Account Number"]
        }
    }

    def parse(self) -> ExtractedData:
        """Multi-strategy parsing with confidence scoring."""
        results = {}
        confidence_scores = {}
        
        for field_name, config in self.FIELD_CONFIG.items():
            value, confidence = self._extract_field(field_name, config)
            results[field_name] = value
            confidence_scores[field_name] = confidence
            
            if value:
                logger.info(f"[Chase] Extracted {field_name}: {value} (confidence: {confidence:.2f})")
            else:
                logger.warning(f"[Chase] Failed to extract {field_name}")
        
        # Populate schema
        self.extracted_data.statement_end_date = self._parse_date(results.get("statement_end_date"))
        self.extracted_data.payment_due_date = self._parse_date(results.get("payment_due_date"))
        self.extracted_data.total_balance = self._clean_amount(results.get("total_balance"))
        self.extracted_data.min_payment_due = self._clean_amount(results.get("min_payment_due"))
        self.extracted_data.card_last_4_digits = self._normalize_card_digits(results.get("card_last_4_digits"))
        
        self.extracted_data.metadata = {
            "provider": self.PROVIDER_NAME,
            "confidence_scores": confidence_scores,
            "extraction_method": "hybrid_multi_strategy"
        }
        
        self._validate_extracted_data()
        return self.extracted_data
    
    def _extract_field(self, field_name: str, config: Dict[str, Any]) -> tuple[Optional[str], float]:
        """Multi-strategy extraction with fallback."""
        # Strategy 1: Regex
        for pattern in config.get("patterns", []):
            value = self._find_by_regex(pattern, self.text)
            if value:
                return value, 0.95
        
        # Strategy 2: Keyword proximity
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
        
        # Strategy 3: Table extraction
        table_data = self._extract_table_data()
        if table_data:
            for table_key in config.get("table_keys", []):
                if table_key in table_data:
                    value = table_data[table_key]
                    if value:
                        return value, 0.75
        
        return None, 0.0
    
    def _normalize_card_digits(self, raw_value: Optional[str]) -> Optional[str]:
        """Extract last 4 digits only."""
        if not raw_value:
            return None
        import re
        digits = re.sub(r'\D', '', raw_value)
        return digits[-4:] if len(digits) >= 4 else digits
    
    def _validate_extracted_data(self) -> None:
        """Validate logical consistency."""
        if self.extracted_data.payment_due_date and self.extracted_data.statement_end_date:
            if self.extracted_data.payment_due_date <= self.extracted_data.statement_end_date:
                logger.warning("[Chase] Payment due date <= statement end date")
        
        if self.extracted_data.min_payment_due and self.extracted_data.total_balance:
            if self.extracted_data.min_payment_due > self.extracted_data.total_balance:
                logger.warning("[Chase] Minimum payment > total balance")