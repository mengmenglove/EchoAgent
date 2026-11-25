#!/bin/bash
# 关闭 EchoAgent 的本地服务。
#   ./scripts/stop.sh              全部关闭：web、api、f5、ollama
#   ./scripts/stop.sh web api      只关指定的几个
#   ./scripts/stop.sh status       只看状态，不关
#
# 按端口找到正在监听的进程，只关命令行符合该服务特征的进程（不会误杀别的项目的 Next.js 或 Python）。
set -u
F5_HOME="${F5_HOME:-$HOME/Documents/LLMWorkSpace/F5-TTS}"
OLLAMA_HOME="${OLLAMA_HOME:-$HOME/Documents/LLMWorkSpace/Ollama}"

# 服务名 端口 进程特征（正则）
SERVICES=(
  "web    3000  next-server|bin/next"
  "api    8000  uvicorn app\.main:app|multiprocessing"
  "f5     8765  tts_server\.py"
  "ollama 11434 ollama serve"
)

listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null; }
cmd_of() { ps -o command= -p "$1" 2>/dev/null; }

# 从监听进程往上找父进程，返回最上层仍符合特征的那个（比如 uvicorn 的重载进程、next dev 主进程），
# 关掉它，它的子进程会跟着退出，不会被自动重启
top_match() {
  local pid=$1 pattern=$2 parent
  while :; do
    parent=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -z "$parent" ] || [ "$parent" -le 1 ] && break
    cmd_of "$parent" | grep -Eq "$pattern" || break
    pid=$parent
  done
  echo "$pid"
}

status() {
  local name port pattern pids
  for line in "${SERVICES[@]}"; do
    read -r name port pattern <<<"$line"
    pids=$(listening "${port}" | tr '\n' ' ')
    if [ -n "$pids" ]; then printf "  %-7s 运行中  端口 %-5s PID %s\n" "${name}" "${port}" "$pids"
    else printf "  %-7s 已停止  端口 %s\n" "${name}" "${port}"; fi
  done
}

stop_one() {
  local name=$1 port=$2 pattern=$3 pids pid targets="" skipped=""
  pids=$(listening "${port}")
  if [ -z "$pids" ]; then echo "  ${name}：没有在运行"; return; fi

  # F5 和 Ollama 优先用它们自己的停止方式（会顺便清理 pid 文件）
  if [ "${name}" = f5 ] && [ -x "$F5_HOME/tts-server-action.sh" ]; then "$F5_HOME/tts-server-action.sh" stop >/dev/null 2>&1; fi
  if [ "${name}" = ollama ] && [ -f "$OLLAMA_HOME/ollama.pid" ]; then
    kill "$(cat "$OLLAMA_HOME/ollama.pid")" 2>/dev/null; rm -f "$OLLAMA_HOME/ollama.pid"
  fi

  for pid in $(listening "${port}"); do
    if cmd_of "$pid" | grep -Eq "$pattern"; then targets="$targets $(top_match "$pid" "$pattern")"
    else skipped="${skipped} $pid"; fi
  done
  [ -n "${skipped}" ] && echo "  ${name}：端口 ${port} 被其他程序占用（PID${skipped}），不是 EchoAgent 的服务，没有关闭"
  # shellcheck disable=SC2086
  [ -n "$targets" ] && kill $targets 2>/dev/null

  # 最多等 10 秒正常退出，还不退就强制结束
  for _ in $(seq 1 20); do [ -z "$(listening "${port}")" ] && break; sleep 0.5; done
  for pid in $(listening "${port}"); do
    cmd_of "$pid" | grep -Eq "$pattern" && kill -9 "$pid" 2>/dev/null
  done
  sleep 0.3
  [ -z "$(listening "${port}")" ] && echo "  ${name}：已关闭" || [ -n "${skipped}" ] || echo "  ${name}：关闭失败，请手动检查端口 ${port}"
}

if [ "${1:-}" = status ]; then status; exit 0; fi
WANT="${*:-web api f5 ollama}"
echo "关闭服务：$WANT"
for line in "${SERVICES[@]}"; do
  read -r name port pattern <<<"$line"
  case " $WANT " in *" ${name} "*) stop_one "${name}" "${port}" "$pattern" ;; esac
done
echo "当前状态："; status
