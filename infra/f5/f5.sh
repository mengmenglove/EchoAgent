#!/bin/bash
# F5-TTS 服务控制：./infra/f5/f5.sh start | stop | status | say "文字"
# F5 的安装位置由 F5_HOME 决定（默认 ~/Documents/LLMWorkSpace/F5-TTS），安装步骤见 docs/INSTALL.md 第 6 节。
set -u
F5_HOME="${F5_HOME:-$HOME/Documents/LLMWorkSpace/F5-TTS}"
PORT="${F5_PORT:-8765}"
URL="http://127.0.0.1:$PORT"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$F5_HOME/.venv/bin/python"
# 权重目录：按 INSTALL.md 装的是 ckpts/；早期手动部署用的是 F5-TTS-ckpts/，两个都认
CK_DIR="$F5_HOME/ckpts/F5TTS_v1_Base"
[ -d "$CK_DIR" ] || [ ! -d "$F5_HOME/F5-TTS-ckpts/F5TTS_v1_Base" ] || CK_DIR="$F5_HOME/F5-TTS-ckpts/F5TTS_v1_Base"
CKPT="$CK_DIR/model_1250000.safetensors"
VOCAB="$CK_DIR/vocab.txt"
PIDFILE="$F5_HOME/f5.pid"
LOG="$F5_HOME/f5.log"

check() {
  [ -x "$PY" ] || { echo "找不到 ${PY}，请先按 docs/INSTALL.md 第 6 节安装 F5"; exit 1; }
  [ -f "$CKPT" ] && [ -f "$VOCAB" ] || { echo "找不到模型权重 ${CKPT}，见 docs/INSTALL.md 6.4"; exit 1; }
  [ -d "$F5_HOME/ffmpeg_dylibs" ] || { echo "找不到 $F5_HOME/ffmpeg_dylibs，见 docs/INSTALL.md 6.3"; exit 1; }
}
healthy() { curl -s -m 2 "$URL/health" 2>/dev/null | grep -q ok; }

start() {
  if healthy; then echo "F5 已在运行：$URL"; return; fi
  check
  echo "启动 F5（首次加载模型约十几秒）..."
  # 必须用 env 直接把 DYLD_FALLBACK_LIBRARY_PATH 传给 python：
  # macOS 的 SIP 会在启动 /bin/bash、nohup 这类系统程序时丢掉 DYLD_* 变量，
  # 只 export 的话传不到 python，torchcodec 就找不到 FFmpeg 库
  nohup env \
    DYLD_FALLBACK_LIBRARY_PATH="$F5_HOME/ffmpeg_dylibs" \
    HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
    F5_CKPT="$CKPT" F5_VOCAB="$VOCAB" F5_PORT="$PORT" \
    "$PY" "$HERE/f5_server.py" >"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 1 120); do
    healthy && { echo "F5 就绪：${URL}（PID $(cat "$PIDFILE")，日志 ${LOG}）"; return; }
    kill -0 "$(cat "$PIDFILE")" 2>/dev/null || break
    sleep 1
  done
  echo "F5 启动失败，日志最后几行："; tail -20 "$LOG"; exit 1
}

stop() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")"; rm -f "$PIDFILE"; echo "F5 已停止"
  else
    rm -f "$PIDFILE"; healthy && echo "F5 在运行但不是本脚本启动的，请用 make stop" || echo "F5 未运行"
  fi
}

say() {
  start >/dev/null
  local out="${2:-/tmp/f5_say.wav}"
  curl -sf -o "$out" -X POST "$URL/tts" -H 'Content-Type: application/json' \
    -d "$("$PY" -c 'import json,sys;print(json.dumps({"text":sys.argv[1]}))' "$1")" \
    && echo "已生成 $out" && { command -v afplay >/dev/null && afplay "$out"; true; }
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) healthy && echo "F5 运行中：$URL" || echo "F5 未运行" ;;
  say) shift; say "$@" ;;
  *) echo "用法：$0 start | stop | restart | status | say \"文字\" [输出.wav]" ;;
esac
