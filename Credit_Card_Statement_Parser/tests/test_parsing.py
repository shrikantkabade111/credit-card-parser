# tests/test_parsing.py

import pytest
from app.parsing.strategies.amex_parser import AmexParser
from app.parsing.strategies.chase_parser import ChaseParser
from app.parsing.main_parser import ParserOrchestrator
from datetime import date

@pytest.fixture
def mock_amex_text():
    """Mock text content for an Amex statement."""
    return """
    AMERICAN EXPRESS
    Page 1 of 5
    Statement Summary
    Cardmember: John Doe
    Account ending in 1001
    
    Closing Date Dec 31, 2025
    Payment Due Date Jan 25, 2026
    
    Total Balance $1,234.56
    Minimum Payment Due $50.00
    """

@pytest.fixture
def mock_chase_text():
    """Mock text content for a Chase statement."""
    return """
    CHASE
    Account Number: **** **** **** 9876
    Statement Period: 11/21/2025 through 12/20/2025
    
    Payment Due Date: 01/15/2026
    New Balance $500.00
    Minimum Payment Due $25.00
    """

def test_amex_parser(mock_amex_text):
    """Test the Amex-specific parser."""
    parser = AmexParser(mock_amex_text)
    data = parser.parse()
    
    assert data.statement_end_date == date(2025, 12, 31)
    assert data.payment_due_date == date(2026, 1, 25)
    assert data.total_balance == 1234.56
    assert data.min_payment_due == 50.00
    assert data.card_last_4_digits == "1001"

def test_chase_parser(mock_chase_text):
    """Test the Chase-specific parser."""
    parser = ChaseParser(mock_chase_text)
    data = parser.parse()
    
    assert data.statement_end_date == date(2025, 12, 20)
    assert data.payment_due_date == date(2026, 1, 15)
    assert data.total_balance == 500.00
    assert data.min_payment_due == 25.00
    assert data.card_last_4_digits == "9876"

def test_parser_identification(mocker, mock_amex_text):
    """Test that the orchestrator correctly identifies Amex."""
    
    # Mock the _extract_text method to just set the text
    mocker.patch.object(ParserOrchestrator, "_extract_text", return_value=None)
    
    # We pass 'None' for content because we're mocking text extraction
    orchestrator = ParserOrchestrator(pdf_content=None)
    orchestrator.full_text = mock_amex_text # Manually set the text
    
    orchestrator._identify_provider() # Run the identification logic
    
    assert orchestrator.provider_name == "Amex"
    assert isinstance(orchestrator.parser_strategy, AmexParser)

def test_parser_identification_fail(mocker):
    """Test that the orchestrator fails gracefully for unknown text."""
    mocker.patch.object(ParserOrchestrator, "_extract_text", return_value=None)
    
    orchestrator = ParserOrchestrator(pdf_content=None)
    orchestrator.full_text = "This is some random text from an unknown bank."
    
    with pytest.raises(ValueError) as e:
        orchestrator._identify_provider()
    
    assert "Could not identify credit card provider" in str(e.value)