# Med Card

Local web app for importing a medical textbook PDF, extracting revision cards, and reviewing them with an uncertain-first draw flow.

## Stack

- Backend: FastAPI
- Frontend: React + Vite
- Database: SQLite
- PDF extraction: pypdf
- LLM: 兼容 DeepSeek 的 OpenAI 风格 API，并提供本地 `mock` 提供者用于烟测

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

本地不接远程模型时，可设置：

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
- `GET /api/textbooks/{textbook_id}/failures`
- `POST /api/textbooks/{textbook_id}/failures/{failure_id}/retry`
- `POST /api/textbooks/{textbook_id}/failures/retry-all`
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

## Notes

- 导入现在在后台执行，并会把进度写入 SQLite。
- 抽取失败的文本块会被落库，可在导入页手动重试。
- 当前版本仍假设 PDF 存在文本层；OCR 只预留了接口，尚未实现。
