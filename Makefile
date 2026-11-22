# 常用命令。每个服务开一个终端窗口分别运行：make f5 / make api / make worker / make web
F5_HOME ?= $(HOME)/Documents/LLMWorkSpace/F5-TTS

.PHONY: deps f5 f5-stop migrate seed api worker web test lint

deps:            ## 启动 Postgres + Redis（需要 Docker）
	docker compose -f infra/docker-compose.yml up -d

f5:              ## 启动本地 F5-TTS 服务
	$(F5_HOME)/tts-server-action.sh start

f5-stop:
	$(F5_HOME)/tts-server-action.sh stop

migrate:         ## 数据库迁移到最新
	cd server && uv run alembic upgrade head

seed:            ## 写入系统音色（读取 server/voices.json）
	cd server && uv run python -m app.cli seed-voices

api:             ## FastAPI，http://127.0.0.1:8000/docs
	cd server && uv run uvicorn app.main:app --reload --port 8000

worker:          ## 任务 Worker（改代码自动重启）
	cd server && uv run arq app.worker.WorkerSettings --watch app

web:             ## 前端，http://localhost:3000
	cd web && npm run dev

test:
	cd server && uv run pytest -q
	cd web && npx tsc --noEmit

lint:
	cd server && uv run ruff check app tests && uv run ruff format --check app tests
	cd web && npm run lint
