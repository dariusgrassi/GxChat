# Gemini Project Context

This document provides context for the GxChat project to the Gemini AI assistant.

## Project Overview

GxChat is a cross-platform chat application that interacts with the GroupMe API. It features a Python (Tkinter) frontend and a Rust (Axum) backend.

### Key Technologies

-   **Frontend:** Python 3.x with Tkinter
-   **Backend:** Rust with Axum
-   **Real-time:** GroupMe's Faye push service and polling
-   **Build/CI:** Docker for the backend, pre-commit for code quality.

### Core Features

-   Channel listing and message history
-   Sending messages
-   Real-time updates for messages and likes
-   User information display

## Development Environment

### Setup

1.  **Backend (Docker):** The Rust backend is containerized using Docker and managed with `docker-compose`. It runs on `http://127.0.0.1:3000`.
2.  **Frontend (Python):** The Python frontend uses `requirements.txt` for dependencies.

### Running the Application

1.  Start the backend: `docker-compose up --build`
2.  Install frontend dependencies: `pip install -r requirements.txt`
3.  Run the frontend: `python main.py`

### Code Quality

-   **Pre-commit:** The project uses pre-commit hooks for both Python and Rust.
    -   **Python:** `ruff` for linting/formatting, `mypy` for type checking.
    -   **Rust:** `rustfmt` for formatting, `clippy` for linting.
-   **CI:** The GitHub Actions workflow in `.github/workflows/ci.yml` runs tests and linting.

## Future Development

For ideas on new features to add, please refer to the [ROADMAP.md](ROADMAP.md) file.

## Project Structure

-   `main.py`: The main entry point for the Python frontend.
-   `backend/`: Contains the Rust backend source code.
-   `requirements.txt`: Python dependencies.
-   `docker-compose.yml`: Docker configuration for the backend.
-   `.pre-commit-config.yaml`: Configuration for pre-commit hooks.
