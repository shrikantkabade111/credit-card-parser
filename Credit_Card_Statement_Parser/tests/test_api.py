# tests/test_api.py

import pytest
from httpx import AsyncClient
from app.main import app
from app.config import settings

# This tells pytest to use asyncio for all test functions
pytestmark = pytest.mark.asyncio

# Use a mock API key for testing
TEST_API_KEY = "test-key-123"
settings.MASTER_API_KEY = TEST_API_KEY

@pytest.fixture(scope="module")
async def async_client():
    """Fixture to create an AsyncClient for testing the app."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def valid_pdf_mock(tmp_path):
    """Fixture to create a mock PDF file."""
    # This is a minimal valid PDF content
    pdf_content = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    p = tmp_path / "test.pdf"
    p.write_bytes(pdf_content)
    return open(p, "rb")

@pytest.fixture
def non_pdf_mock(tmp_path):
    """Fixture to create a mock non-PDF file."""
    p = tmp_path / "test.txt"
    p.write_text("This is not a PDF.")
    return open(p, "rb")

async def test_api_unauthorized(async_client):
    """Test that requests without a valid API key are rejected."""
    response = await async_client.post(
        f"{settings.API_V1_STR}/parse/upload",
        headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401
    assert "Invalid or missing API Key" in response.json()["detail"]

async def test_api_unsupported_media_type(async_client, non_pdf_mock):
    """Test that non-PDF files are rejected."""
    response = await async_client.post(
        f"{settings.API_V1_STR}/parse/upload",
        files={"file": ("test.txt", non_pdf_mock, "text/plain")},
        headers={"X-API-Key": TEST_API_KEY}
    )
    assert response.status_code == 415
    assert "Invalid file type" in response.json()["detail"]
    non_pdf_mock.close()

# Note: Testing the full upload-to-celery-to-result loop
# would require a running Redis and Celery worker,
# making it an integration test.
# Here we will mock the celery task call.

@pytest.mark.skip(reason="Requires mocking celery's apply_async")
async def test_api_upload_success(async_client, valid_pdf_mock, mocker):
    """Test successful file upload and task queuing."""
    
    # Mock the celery task
    mock_apply_async = mocker.patch("app.tasks.parse_statement_task.apply_async")
    mock_task = mocker.Mock()
    mock_task.id = uuid.uuid4()
    mock_apply_async.return_value = mock_task
    
    response = await async_client.post(
        f"{settings.API_V1_STR}/parse/upload",
        files={"file": ("test.pdf", valid_pdf_mock, "application/pdf")},
        headers={"X-API-Key": TEST_API_KEY}
    )
    
    assert response.status_code == 202
    json_resp = response.json()
    assert json_resp["status"] == "PENDING"
    assert "task_id" in json_resp
    assert json_resp["task_id"] == str(mock_task.id)
    
    # Verify apply_async was called once
    mock_apply_async.assert_called_once()
    valid_pdf_mock.close()

async def test_api_get_status_not_found(async_client, mocker):
    """Test checking status for a non-existent task."""
    
    # Mock AsyncResult to return None
    mocker.patch("app.main.AsyncResult", return_value=None)
    
    fake_uuid = uuid.uuid4()
    response = await async_client.get(
        f"{settings.API_V1_STR}/parse/status/{fake_uuid}",
        headers={"X-API-Key": TEST_API_KEY}
    )
    assert response.status_code == 404
    assert "Task not found" in response.json()["detail"]