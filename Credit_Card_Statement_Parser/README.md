# Credit Card Statement Parsing Microservice

This is a production-ready, secure, and scalable microservice for parsing
PDF credit card statements. It uses a modular strategy pattern to support
multiple card issuers and an asynchronous task queue to handle slow
parsing operations.

## Features

- **FastAPI**: High-performance asynchronous API framework.
- **Celery & Redis**: Asynchronous task queuing for non-blocking PDF parsing.
- **Dockerized**: Fully containerized with `docker-compose` for easy setup.
- **Secure**: Uses API Key authentication and handles PII (PDFs) in-memory only.
- **Modular**: Easily extendable "Strategy" pattern to add new bank parsers.
- **Robust**: Handles text-based PDFs and includes stubs for OCR fallbacks.
- **Standardized Output**: Returns clean, validated JSON.

## System Architecture

1.  **Client**: Sends a `POST` request with a PDF file and `X-API-Key` header to the `/api/v1/parse/upload` endpoint.
2.  **FastAPI (`api` service)**:
    - Authenticates the request.
    - Validates the file (is it a PDF?).
    - Reads the file into in-memory bytes.
    - Dispatches a new job to the Celery queue (Redis) with the file bytes.
    - Immediately returns a `202 ACCEPTED` response with a `task_id`.
3.  **Celery (`worker` service)**:
    - Picks up the job from the Redis queue.
    - Instantiates `ParserOrchestrator`.
    - Extracts text using `pdfplumber`.
    - Identifies the provider (Amex, Chase, etc.).
    - Executes the correct `Strategy` (e.g., `AmexParser`).
    - The parser uses regex to find and extract the 5 data points.
    - Saves the final JSON result (or error) to the Celery Result Backend (Redis).
4.  **Client**: Polls the `GET /api/v1/parse/status/{task_id}` endpoint.
5.  **FastAPI**: Reads the result from the Redis backend and returns the final JSON (status: `PENDING`, `SUCCESS`, or `FAILED`) to the client.

## Setup & Running

### Prerequisites

- Docker
- Docker Compose

### 1. Configuration

1.  Copy the example environment file:
    ```sh
    cp .env.example .env
    ```
2.  Generate a secure API key. You can use this command:
    ```sh
    python -c 'import secrets; print(secrets.token_hex(32))'
    ```
3.  Edit the `.env` file and paste your generated key into `MASTER_API_KEY`.

### 2. Build and Run

From the root directory, run:

```sh
docker-compose up --build