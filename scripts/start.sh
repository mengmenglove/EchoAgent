#!/bin/bash
# 一键在后台启动全部服务：make start。日志在 logs/ 下，关闭用 make stop。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
mkdir -p logs
up() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
wait_http() { for _ in $(seq 1 "$2"); do curl -s -m 2 "$1" >/dev/null && return 0; sleep 1; done; return 1; }

make -s ollama || echo "  （Ollama 没启动，聊天功能不可用；其他功能不受影响）"
make -s f5 || { echo "F5 启动失败，先运行 make doctor 检查"; exit 1; }

if up 8000; then echo "后端已在运行"; else
  nohup make -s api >logs/api.log 2>&1 &
  wait_http http://127.0.0.1:8000/api/health 60 && echo "后端已启动（日志 logs/api.log）" || { echo "后端启动失败："; tail -20 logs/api.log; exit 1; }
fi
if up 3000; then echo "前端已在运行"; else
  nohup make -s web >logs/web.log 2>&1 &
  wait_http http://127.0.0.1:3000/login 90 && echo "前端已启动（日志 logs/web.log）" || { echo "前端启动失败："; tail -20 logs/web.log; exit 1; }
fi
echo
curl -s http://127.0.0.1:8000/api/health; echo
echo "打开 http://localhost:3000  （聊天：/chat）    关闭：make stop"
