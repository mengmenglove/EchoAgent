#!/bin/bash
# 检查安装是否完整：make doctor。只读，不改任何东西。每一项缺失都会提示去看 docs/INSTALL.md 的哪一节。
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
F5_HOME="${F5_HOME:-$HOME/Documents/LLMWorkSpace/F5-TTS}"
OLLAMA_HOME="${OLLAMA_HOME:-$HOME/Documents/LLMWorkSpace/Ollama}"
CHAT_MODEL="${CHAT_MODEL:-qwen3.5:4b}"
export PATH="$HOME/Library/Python/3.12/bin:$PATH"
fail=0; warn=0
if [ -t 1 ]; then G=$'\033[32m' R=$'\033[31m' Y=$'\033[33m' N=$'\033[0m'; else G="" R="" Y="" N=""; fi
ok()   { printf "  %s✓%s %s\n" "$G" "$N" "$1"; }
bad()  { printf "  %s✗%s %s  → INSTALL.md %s\n" "$R" "$N" "$1" "$2"; fail=$((fail+1)); }
soft() { printf "  %s!%s %s  → INSTALL.md %s\n" "$Y" "$N" "$1" "$2"; warn=$((warn+1)); }

echo "系统"
[ "$(uname -m)" = arm64 ] && ok "Apple Silicon（arm64）" || bad "不是 arm64，F5 和 Ollama 需要 Apple 芯片" "§1"
mem=$(( $(sysctl -n hw.memsize) / 1073741824 )); [ "$mem" -ge 16 ] && ok "内存 ${mem}GB" || soft "内存 ${mem}GB，建议 16GB 以上" "§1"
free=$(df -g "$HOME" | awk 'NR==2{print $4}'); [ "$free" -ge 15 ] && ok "磁盘剩余 ${free}GB" || soft "磁盘剩余 ${free}GB，完整安装约需 12GB" "§1"

echo "基础工具"
P=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
if [ -x "$P" ] && [ "$("$P" -c 'import platform;print(platform.machine())')" = arm64 ]; then ok "Python 3.12 arm64（${P}）"
else bad "缺少 python.org 的 Python 3.12（arm64）" "§2.1"; fi
command -v uv >/dev/null && ok "uv $(uv --version | awk '{print $2}')" || bad "缺少 uv" "§2.2"
if command -v node >/dev/null; then v=$(node -v | tr -d v | cut -d. -f1); [ "$v" -ge 20 ] && ok "Node.js $(node -v)" || bad "Node.js $(node -v) 太旧，需要 20 以上" "§2.3"
else bad "缺少 Node.js" "§2.3"; fi
command -v ffmpeg >/dev/null && ok "ffmpeg $(ffmpeg -version | head -1 | awk '{print $3}')" || bad "缺少 ffmpeg" "§2.4"
command -v git >/dev/null && ok "git" || bad "缺少 git" "§2.5"

echo "项目"
[ -f "$ROOT/server/.env" ] && ok "server/.env" || bad "缺少 server/.env（make setup 会生成）" "§3"
[ -x "$ROOT/server/.venv/bin/python" ] && ok "后端依赖（server/.venv）" || bad "后端依赖没装" "§3"
[ -d "$ROOT/web/node_modules" ] && ok "前端依赖（web/node_modules）" || bad "前端依赖没装" "§3"
db=$(grep -E '^DATABASE_URL=' "$ROOT/server/.env" 2>/dev/null | cut -d= -f2-)
case "$db" in sqlite*|"") [ -f "$ROOT/server/echo.db" ] && ok "SQLite 数据库已建表" || bad "数据库没建表（make migrate）" "§3" ;;
  *) ok "数据库：${db}（Postgres，请自行确认可连接）" ;; esac

echo "F5-TTS（语音合成）"
if [ -x "$F5_HOME/.venv/bin/python" ]; then
  ok "虚拟环境 $F5_HOME/.venv"
  "$F5_HOME/.venv/bin/python" -c "import f5_tts" 2>/dev/null && ok "f5-tts 已安装" || bad "f5-tts 没装" "§6.2"
  [ "$("$F5_HOME/.venv/bin/python" -c 'import torch;print(torch.backends.mps.is_available())' 2>/dev/null)" = True ] \
    && ok "PyTorch 可以用 GPU（MPS）" || bad "PyTorch 不能用 MPS（可能装成了 x86 版）" "§6.1"
else bad "缺少 $F5_HOME/.venv" "§6.1"; fi
ls "$F5_HOME"/ffmpeg_dylibs/libavutil.*.dylib >/dev/null 2>&1 && ok "FFmpeg 动态库软链" || bad "缺少 ffmpeg_dylibs" "§6.3"
{ [ -f "$F5_HOME/ckpts/F5TTS_v1_Base/model_1250000.safetensors" ] || [ -f "$F5_HOME/F5-TTS-ckpts/F5TTS_v1_Base/model_1250000.safetensors" ]; } \
  && ok "模型权重 F5TTS_v1_Base" || bad "缺少模型权重" "§6.4"
ls "$HOME"/.cache/huggingface/hub/models--charactr--vocos-mel-24khz/snapshots/*/pytorch_model.bin >/dev/null 2>&1 \
  && ok "声码器 vocos-mel-24khz" || soft "声码器还没下载（第一次启动 F5 会自动下载）" "§6.4"

echo "Ollama（聊天模型）"
[ -x "$OLLAMA_HOME/bin/ollama" ] && ok "Ollama $("$OLLAMA_HOME/bin/ollama" --version 2>&1 | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | tail -1)" || soft "缺少 Ollama（只影响聊天功能）" "§7.1"
if [ -d "$OLLAMA_HOME/models/manifests/registry.ollama.ai/library/${CHAT_MODEL%%:*}" ]; then ok "模型 $CHAT_MODEL"
else soft "模型 $CHAT_MODEL 没下载（只影响聊天功能）" "§7.2"; fi

echo "可选"
{ compgen -G "$F5_HOME/voices/*.wav" >/dev/null || compgen -G "$ROOT/server/voices/*.wav" >/dev/null; } && ok "有自定义参考音色" || soft "只有 F5 自带的英文示例音色，中文会带口音" "§8"
ls "$HOME"/.cache/huggingface/hub/models--openai--whisper-large-v3-turbo/snapshots/*/model.safetensors >/dev/null 2>&1 \
  && ok "Whisper（质检用）" || soft "没有 Whisper（只影响默认关闭的质检功能）" "§9"

echo "正在运行的服务"
"$ROOT/scripts/stop.sh" status

echo
if [ "$fail" -eq 0 ]; then echo "✅ 必需项齐全（$warn 个可选提示）。启动：make start"; else echo "❌ 有 $fail 项必需依赖缺失，按提示去 docs/INSTALL.md 对应章节"; exit 1; fi
