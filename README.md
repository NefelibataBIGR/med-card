# Med Card

Local web app for importing a medical textbook PDF, extracting revision cards, and reviewing them with an uncertain-first draw flow.

## Stack

- Backend: FastAPI
- Frontend: React + Vite
- Database: SQLite
- PDF extraction: pypdf
- LLM: DeepSeek-compatible OpenAI-style API, plus a local `mock` provider for smoke tests

## Local Run

1. Create the virtual environment:

```powershell
python -m venv .venv
```

2. Install backend dependencies:

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set `MED_CARD_LLM_API_KEY`.

For local testing without a remote model, set:

```dotenv
MED_CARD_LLM_PROVIDER=mock
```

4. Install frontend dependencies:

```powershell
cd frontend
npm install
```

5. Start the backend:

```powershell
cd ..
$env:PYTHONPATH='backend'
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

6. Start the frontend in another terminal:

```powershell
cd frontend
npm run dev
```

## API

- `POST /api/textbooks/import`
- `GET /api/textbooks`
- `GET /api/cards/draw`
- `POST /api/sessions/{session_id}/reset`
- `PATCH /api/cards/{id}`
- `POST /api/cards/{id}/mark-familiar`
- `POST /api/cards/{id}/mark-uncertain`
- `POST /api/cards/{id}/ignore`
- `DELETE /api/cards/{id}`
- `GET /api/pools/familiar`
- `GET /api/pools/uncertain`

## Validation

- Backend tests:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python -m pytest backend\app\tests -q
```

- Frontend production build:

```powershell
cd frontend
npm run build
```
