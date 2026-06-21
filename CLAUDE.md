# Personal CFO AI — CLAUDE.md

## Project Overview

Personal CFO AI is an early-stage financial management web application. It consists of a Python FastAPI backend and a single-page HTML/JS frontend backed by a local SQLite database. The goal is to provide a personal "Chief Financial Officer" dashboard for tracking accounts, transactions, and financial analysis.

## Repository Structure

```
personal-cfo-ai/
├── CLAUDE.md                  # This file
├── README.md                  # Minimal project description
├── requirements.txt           # Python dependencies
├── dashboard.html             # Single-page frontend (standalone)
├── data/
│   └── finance.db             # SQLite database (auto-created on first run)
└── backend/
    ├── __init__.py
    ├── main.py                # FastAPI app, CORS, router registration
    ├── api/
    │   ├── __init__.py
    │   └── accounts.py        # Account CRUD endpoints
    ├── models/
    │   ├── __init__.py
    │   └── database.py        # SQLAlchemy ORM models + DB setup
    ├── schemas/               # Pydantic validation schemas (currently empty)
    │   └── __init__.py
    └── services/              # Business logic layer (currently empty)
        └── __init__.py
```

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | FastAPI | 0.109.0 |
| ASGI server | Uvicorn | 0.27.0 |
| Data validation | Pydantic | 2.5.3 |
| ORM | SQLAlchemy | 2.0.25 |
| Database | SQLite | (local file) |
| Frontend | Vanilla HTML/CSS/JS | — |
| Python | CPython | 3.11.15 |

Dependencies installed but not yet used: `yfinance` (market data), `requests` (HTTP), `python-dateutil` (date parsing) — reserved for future financial data fetching features.

## Running the Application

### Install dependencies
```bash
pip install -r requirements.txt
```

### Start the backend
```bash
uvicorn backend.main:app --reload --port 8001
```

The API will be available at `http://localhost:8001`. Interactive docs at `http://localhost:8001/docs`.

### Open the frontend
Open `dashboard.html` directly in a browser. The frontend hardcodes `http://localhost:8001` as the API base URL.

### Verify it works
```bash
curl http://localhost:8001/api/health
# {"status":"healthy","database":"connected"}
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Health check / version |
| GET | `/api/health` | Database connectivity check |
| POST | `/api/accounts/` | Create a new account |
| GET | `/api/accounts/` | List all accounts |

All endpoints return JSON. CORS is fully open (`allow_origins=["*"]`) — intended for local development only.

## Data Models

### Account (`accounts` table)
```
id              Integer  PK, auto-increment
name            String   required, max 200 chars
account_type    String   required, max 50 chars (e.g. "checking", "savings", "credit_card", "brokerage")
institution     String   nullable, max 200 chars
current_balance Float    default 0.0
interest_rate   Float    nullable
is_active       Boolean  default True
created_at      DateTime auto-set on insert
updated_at      DateTime auto-set on insert, auto-updated on change
```

### Transaction (`transactions` table — model defined, no API yet)
```
id                Integer  PK
account_id        Integer  FK → accounts.id
date              DateTime required
amount            Float    required
transaction_type  String   max 50 chars
category          String   max 100 chars
merchant          String   max 200 chars
description       Text
created_at        DateTime auto-set on insert
```

## Code Conventions

### Backend (Python)
- **Async routes:** All route handlers use `async def`.
- **Dependency injection:** Database sessions are injected via `Depends(get_db)` — never instantiate `SessionLocal` directly in a route.
- **Pydantic models in routes:** Request body schemas are defined as `BaseModel` subclasses in the route file (e.g. `AccountCreate`). As schemas grow, move them to `backend/schemas/`.
- **Business logic:** Keep route handlers thin. Non-trivial logic belongs in `backend/services/`.
- **ORM queries:** Use SQLAlchemy 2.x style (`db.query(Model).filter(...)`). Avoid raw SQL unless absolutely necessary.
- **No auth yet:** Authentication is not implemented. Do not add protected endpoints without also implementing an auth layer.

### Frontend (JavaScript)
- The entire frontend lives in `dashboard.html` as a single file with embedded CSS and JS.
- The API base URL `http://localhost:8001` is hardcoded as a `const API_BASE` at the top of the `<script>` block — change there to update it globally.
- Fetch calls use plain `async/await` with `try/catch`. Keep this pattern consistent.
- Net worth and other aggregations are computed client-side from the full account list.

### Database
- The SQLite file path is hardcoded in `backend/models/database.py`: `sqlite:///./data/finance.db`. The `data/` directory must exist before starting the server (it is not auto-created).
- Schema is created via `Base.metadata.create_all(engine)` on every startup — safe only because SQLite and SQLAlchemy skip existing tables. For schema changes, you must either drop and recreate the DB or write a migration.
- No migration framework (e.g. Alembic) is configured. Add one before the schema stabilizes.

## Architecture Patterns

```
dashboard.html
    └── fetch() → FastAPI router (api/accounts.py)
                      └── Depends(get_db) → SQLAlchemy Session
                                                └── ORM Model (database.py)
                                                        └── SQLite (data/finance.db)
```

- **Routers** handle HTTP routing and request/response shaping only.
- **Services** (empty) will own business logic and orchestration.
- **Schemas** (empty) will hold reusable Pydantic models separate from route files.
- **Models** own the ORM definitions and DB session factory.

## Development Notes

### What exists vs. what's planned
| Feature | Status |
|---------|--------|
| Account CRUD (create, list) | Implemented |
| Account update / delete endpoints | Missing |
| Transaction API endpoints | Missing (model exists) |
| Net worth calculation | Client-side only |
| Financial data fetching (yfinance) | Dependency present, unused |
| Authentication | Not implemented |
| Input validation / error handling | Minimal |
| Pagination | Not implemented |
| Alembic migrations | Not configured |
| Testing | No tests exist |
| Environment variable config | Not configured |
| CI/CD | Not configured |

### Known issues / gotchas
- The `data/` directory must exist before first run — `Base.metadata.create_all()` does not create it.
- `account.dict()` in `accounts.py:18` uses the deprecated Pydantic v1 API. With Pydantic 2, prefer `account.model_dump()`.
- CORS is fully open; restrict origins before any non-local deployment.
- No `.gitignore` is present — `data/finance.db` and `__pycache__` are tracked by git.
- Port 8001 is hardcoded in both the uvicorn start command convention and `dashboard.html`.

### Adding a new API endpoint
1. Add the route to the appropriate file in `backend/api/` (or create a new router file).
2. If creating a new router, register it in `backend/main.py` with `app.include_router(...)`.
3. Define request/response Pydantic models — in the route file for simple cases, in `backend/schemas/` for reusable ones.
4. Keep business logic in `backend/services/`, not in the route handler.

### Adding a new database model
1. Define the SQLAlchemy model class in `backend/models/database.py`.
2. `Base.metadata.create_all(engine)` will auto-create the table on the next server start (only for new tables).
3. For changes to existing tables, drop and recreate `data/finance.db` during development, or add Alembic.

## Testing

No test suite exists yet. When adding tests:
- Use `pytest` with `httpx.AsyncClient` for API integration tests.
- Use an in-memory SQLite database (`sqlite:///:memory:`) in test fixtures.
- Override the `get_db` dependency in tests to use the test database.

```bash
# Future test command (once tests are added)
pytest backend/tests/
```

## Git Workflow

- Default development branch for AI-assisted work: `claude/claude-md-docs-huguay`
- Main branch: `main`
- Push with: `git push -u origin <branch-name>`
