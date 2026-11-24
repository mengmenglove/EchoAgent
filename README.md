# EchoAgent（回音）

输入需求或文案，AI 自动生成口播语音。

## 文档

- [开发文档与实施计划](docs/DEVELOPMENT_PLAN.md)：架构、数据模型、API、Agent、TTS、计费、部署、里程碑和关键库详解
- [代码解读](docs/CODE_WALKTHROUGH.md)：逐文件讲解实现、请求的完整旅程、踩过的坑、动手练习

## 结构

- `web/`：前端（Next.js）
- `server/`：后端（FastAPI + Claude Agent，任务默认在进程内执行，可选 Redis + arq Worker），调用本地 F5-TTS 服务 `http://127.0.0.1:8765/tts` 合成语音
- `infra/`：可选依赖（Postgres、Redis、MinIO）

## 本地开发

详细步骤见 [代码解读 · 第 1 节](docs/CODE_WALKTHROUGH.md#1-先把项目跑起来)。简要流程：

```bash
make setup   # 首次：生成 server/.env、装依赖、建表、写入音色
make f5      # 终端 1：F5-TTS
make api     # 终端 2：http://127.0.0.1:8000/docs
make web     # 终端 3：http://localhost:3000
```

默认用 SQLite、不用 Redis。需要 Postgres / Redis 时改 `server/.env`，再执行 `make deps` 和 `make worker`。

测试：`cd server && uv run pytest -q`
