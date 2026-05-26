# Med Card

本地运行的医学教材概念卡片工具。

它会导入教材 PDF，按段落提取主概念，并生成一段一张的复习卡片。卡片包含：

- 概念名
- 英文名（如果段落中有）
- 介绍
- 教材页码
- 章节路径
- 原文段落

## 当前行为

- 抽取单位是“段落”，不是整章，也不是整页。
- 每个段落最多提取 1 个主概念卡。
- 章节标题只作为定位信息保留，不单独生成卡片。
- 卡片优先记录教材正文里印刷出来的页码，不使用 PDF 物理页码冒充教材页码。
- 重新导入 PDF 会覆盖旧教材、旧卡片和旧失败记录。

## 技术栈

- Backend: FastAPI
- Frontend: React + Vite
- Database: SQLite
- PDF extraction: pypdf
- LLM: 兼容 OpenAI 风格接口，默认可配置为 DeepSeek，也支持本地 `mock`

## 环境要求

- Python 3.11+ 推荐
- Node.js 18+ 推荐
- Windows PowerShell

## 安装

在项目根目录执行：

```powershell
cd F:\GitHub仓库\med_card

python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt

Copy-Item .env.example .env

cd frontend
npm install
cd ..
```

## 配置

编辑 `.env`。

### 本地测试模式

如果你先只想验证流程，不调用远程模型：

```dotenv
MED_CARD_LLM_PROVIDER=mock
```

### 远程模型模式

如果你要调用真实模型，至少配置：

```dotenv
MED_CARD_LLM_PROVIDER=deepseek
MED_CARD_LLM_API_KEY=你的_api_key
```

`.env.example` 里还提供了这些可选项：

- `MED_CARD_LLM_BASE_URL`
- `MED_CARD_LLM_MODEL`
- `MED_CARD_CORS_ORIGINS`

## 运行

### 启动后端

打开一个终端：

```powershell
cd F:\GitHub仓库\med_card
$env:PYTHONPATH='backend'
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

后端默认地址：

- `http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`

### 启动前端

再打开一个终端：

```powershell
cd F:\GitHub仓库\med_card\frontend
npm run dev
```

前端默认地址：

- `http://127.0.0.1:5173`

## 使用说明

1. 打开前端页面。
2. 上传一本教材 PDF。
3. 系统会清空旧数据，并重新导入当前 PDF。
4. 导入完成后，在抽卡页按段落生成的概念卡进行复习。
5. 可以把卡片标记为熟悉、模糊、忽略，也可以手动编辑。
6. 如果某些段落抽取失败，可以在导入页重试。

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

## 验证

### 后端测试

```powershell
cd F:\GitHub仓库\med_card
$env:PYTHONPATH='backend'
.\.venv\Scripts\python -m pytest backend\app\tests -q
```

### 前端构建

```powershell
cd F:\GitHub仓库\med_card\frontend
npm run build
```

## 当前限制

- 当前只支持“有文本层”的 PDF。
- 扫描版 PDF 还没有 OCR。
- 教材页码识别依赖页眉/页脚附近的独立数字；如果某本书版式特殊，可能会出现个别页识别不到的情况。

## 相关目录

- 后端入口：[backend/app/main.py](backend/app/main.py)
- 抽取逻辑：[backend/app/services/text_extraction.py](backend/app/services/text_extraction.py)
- 导入逻辑：[backend/app/services/textbook_importer.py](backend/app/services/textbook_importer.py)
- LLM 抽卡逻辑：[backend/app/services/llm.py](backend/app/services/llm.py)
- 前端主界面：[frontend/src/App.tsx](frontend/src/App.tsx)
