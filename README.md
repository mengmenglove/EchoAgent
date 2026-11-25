# EchoAgent（回音）

输入需求或文案，AI 自动生成口播语音。

## 文档

- [**安装说明**](docs/INSTALL.md)：从一台新 Mac 开始，装齐 Python、Node、ffmpeg、F5-TTS、Ollama 等全部依赖
- [开发文档与实施计划](docs/DEVELOPMENT_PLAN.md)：架构、数据模型、API、Agent、TTS、计费、部署、里程碑和关键库详解
- [代码解读](docs/CODE_WALKTHROUGH.md)：逐文件讲解实现、请求的完整旅程、踩过的坑、动手练习

## 结构

- `web/`：前端（Next.js）
- `server/`：后端（FastAPI + Claude Agent，任务默认在进程内执行，可选 Redis + arq Worker），调用本地 F5-TTS 服务 `http://127.0.0.1:8765/tts` 合成语音
- `infra/`：可选依赖（Postgres、Redis、MinIO）

## 本地开发

第一次安装请看 [docs/INSTALL.md](docs/INSTALL.md)。装好后：

```bash
make doctor   # 检查依赖是否齐全
make start    # 后台启动全部服务，打开 http://localhost:3000
make stop     # 不用时关闭
```

也可以分开启动：

```bash
make setup   # 首次：生成 server/.env、装依赖、建表、写入音色
make f5      # 终端 1：F5-TTS
make api     # 终端 2：http://127.0.0.1:8000/docs
make web     # 终端 3：http://localhost:3000

# 语音聊天（本地 Qwen3.5-4B + F5）：
make ollama && make ollama-pull   # 第一次下载约 3.4GB，之后只需 make ollama

# 不用的时候
make stop     # 关闭全部服务（web、api、f5、ollama）
make status   # 查看哪些在运行
```

默认用 SQLite、不用 Redis。需要 Postgres / Redis 时改 `server/.env`，再执行 `make deps` 和 `make worker`。

测试：`cd server && uv run pytest -q`
