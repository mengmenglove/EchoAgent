# 第一次：make setup。之后每个服务开一个终端：make f5 / make api / make web
# 默认用 SQLite、不用 Redis。deps 和 worker 只有换成 Postgres / Redis 时才需要。
export PATH := $(HOME)/Library/Python/3.12/bin:$(PATH)
F5_HOME ?= $(HOME)/Documents/LLMWorkSpace/F5-TTS

.PHONY: setup deps f5 f5-stop migrate seed api worker web test lint

setup:           ## 首次准备：生成 server/.env、装依赖、建表、写入音色（可重复执行）
	@test -f server/.env || { sed "s|^JWT_SECRET=$$|JWT_SECRET=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')|" server/.env.example > server/.env && chmod 600 server/.env && echo "已生成 server/.env"; }
	cd server && uv sync --frozen
	$(MAKE) migrate seed
	test -d web/node_modules || (cd web && npm ci)

deps:            ## 可选：启动 Postgres + Redis（需要 Docker）
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
	cd server && uv run uvicorn app.main:app --reload --reload-dir app --port 8000 --timeout-graceful-shutdown 3

worker:          ## 可选：任务 Worker，配了 REDIS_URL 才需要（改代码自动重启）
	cd server && uv run arq app.worker.WorkerSettings --watch app

web:             ## 前端，http://localhost:3000
	cd web && npm run dev

test:
	cd server && uv run pytest -q
	cd web && npx tsc --noEmit

lint:
	cd server && uv run ruff check app tests && uv run ruff format --check app tests
	cd web && npm run lint
