# EchoAgent（回音）

输入需求或文案，AI 自动生成口播语音。

## 结构

- `web/`：前端（Next.js）
- `server/`：后端（FastAPI，规划中），调用本地 F5-TTS 服务 `http://127.0.0.1:8765/tts` 合成语音

## 本地开发

```bash
cd web && npm install && npm run dev
```
