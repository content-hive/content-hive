# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file is a lightweight Claude adapter.
For full project conventions and architecture rules, use:
- `.github/copilot-instructions.md` (source of truth)

## Project Overview

Content Hive is a FastAPI-based content parsing service (port 6123) with a plugin-driven architecture. It runs on Python 3.13, uses SQLite via SQLAlchemy ORM, and is deployed via Docker.

## Commands

**Development (Docker):**
```bash
make up       # Build and start the service
make down     # Stop the service
```

**Dependencies:**
```bash
uv sync       # Install dependencies into .venv
uv lock       # Update lock file
```

**Lint / Format:**
```bash
ruff check .       # Lint
ruff format .      # Format
ruff check --fix . # Auto-fix lint issues
```

There is no configured test suite in this project.

**Run locally (without Docker):**
```bash
uv run uvicorn contenthive.main:app --host 0.0.0.0 --port 6123
```

## Fast Facts

- Port: `6123`
- Runtime: Python `3.13`
- Stack: FastAPI + SQLAlchemy + SQLite
- Persistent volume: `/config` (data, logs, plugins)
