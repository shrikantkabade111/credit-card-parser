# app/parsing/strategies/base_parser.py

from abc import ABC, abstractmethod
from app.schemas import ExtractedData
import re
from datetime import datetime, date  # Import date
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """
    Abstract Base Class for all statement parsers.
    
    Provides robust helper methods for multi-strategy parsing:
    - Regex-based extraction
    - Keyword proximity search
    - Table extraction
    - Validation utilities
    """
    
    # Common regex patterns
    AMOUNT_REGEX = r"\$?([\d,]+\.\d{2})"  # Captures: $1,234.56, 1234.56
    # Flexible date regex
    DATE_REGEX = r"(\d{1,2}/\d{1,2}/\d{2,4})|(\w+\.?\s+\d{1,2},?\s+\d{4})|(\d{4}-\d{2}-\d{2})"
    CARD_DIGITS_REGEX = r"[\*xX\.]{4,}[\s\-]?(\d{4})"  # Matches: ****1234, xxxx-1234

    def __init__(self, text: str):
        """
        Initializes the parser with extracted PDF text.
        
        :param text: Full plain text content of the PDF.
        """
        self.text = text
        self.text_lower = text.lower()
        self.extracted_data = ExtractedData()
        self._table_cache: Optional[Dict[str, str]] = None

    @abstractmethod
    def parse(self) -> ExtractedData:
        """Main parsing method - must be implemented by subclasses."""
        raise NotImplementedError

    def get_result(self) -> ExtractedData:
        """Returns the extracted data object."""
        return self.extracted_data

    # ========== CORE HELPER METHODS ==========

    @staticmethod
    def _find_by_regex(pattern: str, text: str) -> Optional[str]:
        """
        Finds first match using regex, returns the first non-empty group.
        
        :param pattern: Regex pattern with capturing groups
        :param text: Text to search
        :return: First non-empty captured group or None
        """
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            # Return first non-empty group
            for group in match.groups():
                if group:
                    return group.strip()
        return None

    @staticmethod
    def _clean_amount(amount_str: Optional[str]) -> Optional[float]:
        """
        Cleans and converts currency strings to float.
        
        Examples: "$1,234.56" → 1234.56, "1234.56" → 1234.56
        """
        if not amount_str:
            return None
        
        # Remove currency symbols, commas, spaces
        cleaned = re.sub(r"[$,\s]", "", str(amount_str))
        
        try:
            value = float(cleaned)
            return round(value, 2)  # Ensure 2 decimal places
        except (ValueError, TypeError):
            logger.warning(f"Could not parse amount: {amount_str}")
            return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[date]:  # <-- FIX 1: Return type is date
        """
        Parses various date formats into date object (not datetime).
        
        Supports: 12/31/25, 12/31/2025, Dec 31 2025, 2025-12-31
        """
        if not date_str:
            return None
        
        # Clean up the date string
        date_str = date_str.strip().replace('.', '').replace(',', '')
        
        common_formats = [
            '%m/%d/%y',      # 12/31/25
            '%m/%d/%Y',      # 12/31/2025
            '%d/%m/%y',      # 31/12/25 (European)
            '%d/%m/%Y',      # 31/12/2025
            '%b %d %Y',      # Dec 31 2025
            '%B %d %Y',      # December 31 2025
            '%Y-%m-%d',      # 2025-12-31
            '%d-%m-%Y',      # 31-12-2025
        ]
        
        for fmt in common_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.date()  # <-- FIX 2: Convert datetime to date
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str}")
        return None

    # ========== ADVANCED PROXIMITY SEARCH ==========

    def _find_proximity_match(
        self, 
        keyword: str, 
        pattern: str, 
        window: int = 150,
        search_backward: bool = False
    ) -> Optional[str]:
        """
        Finds a pattern within a character window near a keyword.
        
        :param keyword: Keyword to search for (case-insensitive)
        :param pattern: Regex pattern to match
        :param window: Character window size to search
        :param search_backward: If True, searches before keyword instead of after
        :return: Matched pattern or None
        """
        try:
            keyword_index = self.text_lower.index(keyword.lower())
            
            if search_backward:
                search_start = max(0, keyword_index - window)
                search_end = keyword_index
            else:
                search_start = keyword_index + len(keyword)
                search_end = min(len(self.text), search_start + window)
            
            search_area = self.text[search_start:search_end]
            return self._find_by_regex(pattern, search_area)
            
        except ValueError:
            logger.debug(f"Keyword '{keyword}' not found in text")
            return None

    def _find_date_near_keyword(self, keyword: str, window: int = 150) -> Optional[str]:
        """Finds date near a keyword."""
        return self._find_proximity_match(keyword, self.DATE_REGEX, window)

    def _find_amounts_near_keyword(self, keyword: str, window: int = 150) -> Optional[str]:
        """Finds amount near a keyword."""
        return self._find_proximity_match(keyword, self.AMOUNT_REGEX, window)

    def _find_text_near_keyword(
        self, 
        keyword: str, 
        pattern: str = r"([A-Za-z0-9\s\-\.]+)",
        window: int = 100
    ) -> Optional[str]:
        """Finds text pattern near a keyword."""
        return self._find_proximity_match(keyword, pattern, window)

    # ========== CARD NUMBER EXTRACTION ==========

    def _find_last4_card(self) -> Optional[str]:
        """
        Extracts last 4 digits of card number from various formats.
        
        Handles: Account Ending 1234, ****1234, xxxx-1234, etc.
        """
        patterns = [
            r"Account\s+Ending\s*-?\s*(\d{4,5})",
            r"Card\s+(?:Number\s+)?Ending\s*[:\-]?\s*(\d{4,5})",
            r"Account\s*(?:#|Number)\s*[\*xX\.]+[\s\-]?(\d{4})",
            r"Card\s*(?:#|Number)?\s*[\*xX\.]+[\s\-]?(\d{4})",
            self.CARD_DIGITS_REGEX
        ]
        
        for pattern in patterns:
            match = self._find_by_regex(pattern, self.text)
            if match:
                # Extract only digits and take last 4
                digits = re.sub(r'\D', '', match)
                return digits[-4:] if len(digits) >= 4 else digits
        
        return None

    # ========== TABLE EXTRACTION ==========

    def _extract_table_data(self) -> Dict[str, str]:
        """
        Extracts structured key-value pairs from the document.
        
        Uses caching to avoid redundant processing.
        Looks for patterns like:
        - "Key Value" (whitespace separated)
        - "Key: Value" (colon separated)
        - Table-like structures
        """
        if self._table_cache is not None:
            return self._table_cache
        
        table = {}
        
        # Pattern: "Key    Value" (multi-space or tab separated)
        # Examples: "New Balance    $1,234.56"
        table_patterns = [
            r"^(New Balance|Total Balance|Balance Due)\s{2,}(.+)$",
            r"^(Payment Due Date|Due Date)\s{2,}(.+)$",
            r"^(Minimum Payment Due|Minimum Payment|Min Payment)\s{2,}(.+)$",
            r"^(Closing Date|Statement Date|Statement End Date)\s{2,}(.+)$",
            r"^(Account Ending|Card Ending)\s{2,}(.+)$",
        ]
        
        # Process line by line
        for line in self.text.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            for pattern in table_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    key = match.group(1).strip().title()
                    value = match.group(2).strip()
                    
                    # Only take first occurrence
                    if key not in table:
                        table[key] = value
        
        self._table_cache = table
        return self._table_cache

    # ========== VALIDATION UTILITIES ==========

    def _safe_amount(self, value: any) -> Optional[float]:
        """Safely converts any value to float amount."""
        if value is None:
            return None
        return self._clean_amount(str(value))

    def _validate_date_range(
        self, 
        start_date: Optional[datetime], 
        end_date: Optional[datetime]
    ) -> bool:
        """Validates that end_date is after start_date."""
        if not start_date or not end_date:
            return True  # Can't validate if either is missing
        return end_date > start_date

    def _validate_amount_range(
        self, 
        amount: Optional[float], 
        min_val: float = 0.0, 
        max_val: float = 1_000_000.0
    ) -> bool:
        """Validates amount is within reasonable range."""
        if amount is None:
            return True
        return min_val <= amount <= max_val