# EchoAgent 安装说明

从一台全新的 Mac 开始，把 EchoAgent 的所有依赖装好。按章节顺序做，每一节最后都有一个"验证"步骤，通过了再往下走。

全部装完后，运行 `make doctor`，它会逐项检查，缺什么就告诉你看本文的哪一节。

---

## 目录

1. [机器要求](#1-机器要求)
2. [基础工具](#2-基础工具)：Python 3.12、uv、Node.js、ffmpeg、git
3. [项目本身](#3-项目本身)
4. [国内网络镜像速查](#4-国内网络镜像速查)
5. [目录布局](#5-目录布局)
6. [F5-TTS（语音合成）](#6-f5-tts语音合成)
7. [Ollama + Qwen3.5-4B（聊天）](#7-ollama--qwen35-4b聊天)
8. [中文参考音色](#8-中文参考音色)
9. [可选组件](#9-可选组件)：Whisper、Claude、Postgres / Redis
10. [启动、关闭、检查](#10-启动关闭检查)
11. [常见问题](#11-常见问题)

**各部分的作用**：

| 组件 | 用途 | 必需吗 |
|---|---|---|
| Python 3.12 + uv | 后端 | 必需 |
| Node.js | 前端网页 | 必需 |
| ffmpeg | 音频转码、响度标准化 | 必需 |
| F5-TTS | 把文字合成语音 | 必需 |
| Ollama + Qwen3.5-4B | 语音聊天 | 只有聊天功能需要 |
| 中文参考音色 | 让中文发音自然 | 强烈建议 |
| Whisper | 质检（检查读错的字） | 可选，默认关闭 |
| Claude API | "说需求，AI 写稿"模式 | 可选 |
| Postgres / Redis | 上线、多进程部署 | 可选，本地开发不需要 |

---

## 1. 机器要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 芯片 | **Apple Silicon（M1 及以后）** | F5 和 Ollama 要用 Apple GPU（MPS / Metal）加速；Intel Mac 上 PyTorch 最高只到 2.2，装不了 F5 的新版依赖 |
| 内存 | 16GB 以上，推荐 32GB | F5 约 3GB，Qwen3.5-4B 约 4GB，再加上浏览器和开发工具 |
| 磁盘 | 预留 15GB | 见下表 |
| 系统 | macOS 13 以上 | |

**磁盘占用明细**：

| 内容 | 大小 |
|---|---|
| F5 虚拟环境（PyTorch 等） | ~1.8GB |
| F5 模型权重 + 声码器 | ~1.4GB |
| Ollama 程序 | ~0.6GB |
| Qwen3.5-4B 模型 | ~3.7GB |
| 后端 + 前端依赖 | ~1GB |
| Whisper（可选） | ~1.6GB |

**验证**：

```bash
uname -m                                              # 必须输出 arm64
sysctl -n hw.memsize | awk '{print $1/1073741824 " GB"}'
df -h ~ | tail -1
```

---

## 2. 基础工具

### 2.1 Python 3.12（arm64 原生）

**必须是 arm64 原生的 Python**。如果装成了 Intel（x86_64）版，所有 Python 包都会按 Intel 安装，PyTorch 被卡在 2.2.2，F5 的依赖装不上，而且报错信息很难看懂（比如 `numpy has no attribute long`、`PyTorch>=2.6 required`）。

推荐用 python.org 的官方安装包，它是 universal2 版本，在 M 芯片上会以 arm64 运行。不推荐用 Homebrew 装，国内首次使用 Homebrew 经常卡在下载 portable-ruby。

```bash
# 国内用华为云镜像，速度快
curl -fL -o /tmp/python-3.12.8-macos11.pkg \
  https://mirrors.huaweicloud.com/python/3.12.8/python-3.12.8-macos11.pkg
# 海外用官方源：https://www.python.org/ftp/python/3.12.8/python-3.12.8-macos11.pkg

sudo installer -pkg /tmp/python-3.12.8-macos11.pkg -target /
```

**验证**：

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
  -c "import platform, sys; print(sys.version.split()[0], platform.machine())"
# 期望：3.12.8 arm64
```

> 以下所有命令里的 `python3.12`，指的都是这个完整路径。它被加进了 PATH（安装包会自动修改 `~/.zprofile`），所以也可以直接写 `python3.12`。

### 2.2 uv（Python 依赖管理）

```bash
python3.12 -m pip install --user uv -i https://pypi.tuna.tsinghua.edu.cn/simple

# uv 装在 ~/Library/Python/3.12/bin，把它永久加进 PATH
echo 'export PATH="$HOME/Library/Python/3.12/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**验证**：`uv --version` 能输出版本号，比如 `uv 0.13.9`。

> 项目的 `Makefile` 会自动把这个目录加进 PATH，所以就算没改 `~/.zshrc`，`make` 命令也能用。但自己在终端里直接敲 `uv` 时需要它在 PATH 里。

### 2.3 Node.js（22 LTS）

前端用的是 Next.js 16，需要 Node 20 以上，推荐 22。

```bash
# 国内用 npmmirror 镜像
curl -fL -o /tmp/node.tar.gz \
  https://npmmirror.com/mirrors/node/v22.22.2/node-v22.22.2-darwin-arm64.tar.gz
# 海外：https://nodejs.org/dist/v22.22.2/node-v22.22.2-darwin-arm64.tar.gz

sudo mkdir -p /usr/local/lib/nodejs
sudo tar -xzf /tmp/node.tar.gz -C /usr/local/lib/nodejs
echo 'export PATH="/usr/local/lib/nodejs/node-v22.22.2-darwin-arm64/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

也可以从 [nodejs.org](https://nodejs.org) 下载 `.pkg` 安装包，双击安装。

国内网络下，可以把 npm 源也换成镜像：

```bash
npm config set registry https://registry.npmmirror.com
```

**验证**：`node -v` 输出 `v22.x`，`npm -v` 能输出版本号。

### 2.4 ffmpeg

后端用它把音频转成 mp3、做响度标准化，以及转码用户上传的参考音频。

**方式一：Homebrew**（已经装了 Homebrew 的话最简单）

```bash
brew install ffmpeg
```

**方式二：直接下载静态编译版**（没有 Homebrew，或者 brew 装不上时）

到 [osxexperts.net](https://www.osxexperts.net/) 下载 **Apple Silicon** 版的 ffmpeg 压缩包，解压后：

```bash
sudo mkdir -p /usr/local/bin
sudo mv ffmpeg /usr/local/bin/ && sudo chmod +x /usr/local/bin/ffmpeg
xattr -d com.apple.quarantine /usr/local/bin/ffmpeg 2>/dev/null   # 解除"无法验证开发者"拦截
```

**验证**：`ffmpeg -version | head -1` 能输出版本，要求 4 以上。

> 如果你之前装过 Intel 版的 ffmpeg（`file $(which ffmpeg)` 显示 `x86_64`），也能用，因为 Rosetta 会自动转译，只是慢一点。

> 注意：这个 ffmpeg 是给 **EchoAgent 后端**用的命令行工具。F5 内部解码音频用的是另一套 FFmpeg 动态库，在 6.3 节单独处理，两者互不影响。

### 2.5 git

macOS 自带 git，第一次运行时会提示安装"命令行开发者工具"：

```bash
git --version          # 没装的话会弹出安装窗口，点"安装"即可
# 或者手动触发：xcode-select --install
```

如果要用 SSH 方式推送到 GitHub，还需要配置 SSH key：

```bash
ssh-keygen -t ed25519 -C "你的邮箱"
cat ~/.ssh/id_ed25519.pub     # 复制，到 GitHub → Settings → SSH and GPG keys 添加
ssh -T git@github.com         # 显示 "Hi 用户名!" 就成功了
```

---

## 3. 项目本身

```bash
mkdir -p ~/Documents/LLMWorkSpace/EchoAgent && cd ~/Documents/LLMWorkSpace/EchoAgent
git clone git@github.com:mengmenglove/EchoAgent.git echo-agent
cd echo-agent

make setup
```

`make setup` 做了这几件事（可以重复执行，已经完成的步骤会跳过）：

1. 从 `server/.env.example` 复制出 `server/.env`，并自动生成一个随机的 `JWT_SECRET`
2. `uv sync --frozen`：按 `server/uv.lock` 锁定的版本安装后端依赖到 `server/.venv`
3. `alembic upgrade head`：创建数据库表（默认是 SQLite 文件 `server/echo.db`）
4. `seed-voices`：写入系统音色。还没配置中文音色时，会先用 F5 自带的英文示例
5. `npm ci`：安装前端依赖到 `web/node_modules`

> 第 4 步需要 F5 已经装好，因为它要读取 F5 自带的示例音频。如果你是先装项目、后装 F5，装完 F5 后再运行一次 `make seed` 就行。

**验证**：

```bash
cd server && uv run pytest -q     # 全部通过（约 12 秒，不需要 F5、Ollama 等任何外部服务）
```

---

## 4. 国内网络镜像速查

安装过程中会从这些地方下载，国内直连常常很慢甚至失败：

| 下载内容 | 官方源 | 国内替代 | 怎么用 |
|---|---|---|---|
| Python 包（pip / uv） | pypi.org | 清华 `https://pypi.tuna.tsinghua.edu.cn/simple` | pip 加 `-i 地址`；本项目的 `server/pyproject.toml` 已经默认配好了清华源 |
| Hugging Face 模型 | huggingface.co | `https://hf-mirror.com` | `export HF_ENDPOINT=https://hf-mirror.com` |
| GitHub Release 文件 | github.com | `https://gh-proxy.com/` 加在原地址前面 | 例：`https://gh-proxy.com/https://github.com/...` |
| npm 包 | registry.npmjs.org | `https://registry.npmmirror.com` | `npm config set registry ...` |
| Node.js 安装包 | nodejs.org | `https://npmmirror.com/mirrors/node/` | 见 2.3 |
| Python 安装包 | python.org | `https://mirrors.huaweicloud.com/python/` | 见 2.1 |
| Ollama 模型 | registry.ollama.ai | 无可靠镜像，直连通常 0.5～2MB/s | 耐心等，或者见 7.2 的备选方案 |

> 第三方镜像可能随时变化。从镜像下载的**程序文件**，一定要核对官方公布的 SHA256 校验值（7.1 节有例子）。

---

## 5. 目录布局

所有大模型相关的东西都统一放在 `~/Documents/LLMWorkSpace/` 下，方便管理和清理：

```
~/Documents/LLMWorkSpace/
├── EchoAgent/echo-agent/     本项目（git 仓库）
├── F5-TTS/                   语音合成：虚拟环境、模型权重、FFmpeg 库、参考音色
│   ├── .venv/
│   ├── ckpts/F5TTS_v1_Base/
│   ├── ffmpeg_dylibs/
│   ├── voices/               你录制的参考音频
│   ├── f5.log  f5.pid        运行日志（自动生成）
└── Ollama/                   本地大模型
    ├── bin/ollama            程序
    ├── models/               模型文件（Qwen3.5-4B 在这里）
    └── logs/ollama.log
```

位置不一样也没关系，在命令前面设置环境变量覆盖默认路径即可，比如 `F5_HOME=/其他路径 make f5`、`OLLAMA_HOME=/其他路径 make ollama`。

另外，Hugging Face 的模型（F5 的声码器、Whisper）会自动缓存到 `~/.cache/huggingface/hub/`，这是 Hugging Face 的默认位置。

---

## 6. F5-TTS（语音合成）

F5-TTS 是上海交大开源的语音合成模型，支持中英文和零样本音色克隆：给它一段几秒钟的参考录音，它就能用这个声音念任何文字。

- 代码：https://github.com/SWivid/F5-TTS
- 权重：https://huggingface.co/SWivid/F5-TTS

EchoAgent 通过 HTTP 调用一个**常驻的 F5 服务**（`127.0.0.1:8765`），这样模型只需要加载一次，之后每句话只要几秒。服务脚本在本仓库的 `infra/f5/` 目录下，F5 本身（虚拟环境和模型）装在仓库外面的 `F5_HOME` 里。

### 6.1 创建虚拟环境，安装 PyTorch

```bash
export F5_HOME=~/Documents/LLMWorkSpace/F5-TTS
mkdir -p "$F5_HOME" && cd "$F5_HOME"

# 一定要用 2.1 节装的 arm64 Python
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -m venv .venv
.venv/bin/python -c "import platform; print(platform.machine())"      # 必须是 arm64

PIP="-i https://pypi.tuna.tsinghua.edu.cn/simple"
.venv/bin/python -m pip install -U pip $PIP
.venv/bin/python -m pip install torch torchaudio $PIP
```

**验证 GPU 可用**：

```bash
.venv/bin/python -c "import torch; print(torch.__version__, 'MPS:', torch.backends.mps.is_available())"
# 期望：2.x.x MPS: True
```

如果显示 `MPS: False`，基本可以确定 Python 不是 arm64 版，回到 2.1 节检查。

### 6.2 安装 f5-tts

```bash
cd "$F5_HOME"
.venv/bin/python -m pip install f5-tts --prefer-binary $PIP
.venv/bin/python -m pip install av $PIP
```

- `--prefer-binary`：优先使用预编译包。不加的话，`llvmlite`、`cryptography` 这类包可能会从源码编译，非常慢甚至卡住。如果还是卡在编译，改用 `--only-binary=:all:`
- `av`（PyAV）：它自带一份 arm64 的 FFmpeg 动态库，下一步要用到

**验证**：

```bash
.venv/bin/python -c "import f5_tts, torch, transformers, numpy; print('ok', transformers.__version__, numpy.__version__)"
```

**实测可用的版本组合**（2026 年 11 月，M3 Pro）：f5-tts 1.1.22、torch 2.15.0、torchaudio 2.11.1、torchcodec 0.17.0、transformers 5.22.1、numpy 2.5.4、av 19.0.2。以后遇到不兼容的问题，可以先锁定到这组版本试试，例如 `pip install "f5-tts==1.1.22" "torch==2.15.0"`。

### 6.3 FFmpeg 动态库（关键步骤）

新版 torchaudio 是通过 `torchcodec` 读取音频的，而 torchcodec 需要系统里有 FFmpeg 的**动态库**（`.dylib` 文件），光有 2.4 节的 ffmpeg 命令行工具是不够的。

PyAV 自带了这些库，但文件名带有完整版本号（例如 `libavcodec.62.11.100.dylib`），而 torchcodec 按主版本号去找（`libavcodec.62.dylib`）。所以需要建一组标准名字的软链接：

```bash
cd "$F5_HOME"
AVDYLIB="$(.venv/bin/python -c 'import av, os; print(os.path.join(os.path.dirname(av.__file__), ".dylibs"))')"
mkdir -p ffmpeg_dylibs
for f in "$AVDYLIB"/libav*.dylib "$AVDYLIB"/libsw*.dylib; do
  [ -f "$f" ] || continue
  base=$(basename "$f")
  ln -sf "$f" "ffmpeg_dylibs/$(echo "$base" | sed -E 's/\.([0-9]+)\.[0-9]+\.[0-9]+\.dylib/.\1.dylib/')"   # libavcodec.62.dylib
  ln -sf "$f" "ffmpeg_dylibs/$(echo "$base" | sed -E 's/\.[0-9]+\.[0-9]+\.[0-9]+\.dylib/.dylib/')"       # libavcodec.dylib
done
ls ffmpeg_dylibs
```

**验证 torchcodec 能解码音频**：

```bash
EX="$(.venv/bin/python -c 'from importlib.resources import files; print(files("f5_tts") / "infer/examples/basic/basic_ref_en.wav")')"
env DYLD_FALLBACK_LIBRARY_PATH="$F5_HOME/ffmpeg_dylibs" .venv/bin/python -c "
from torchcodec.decoders import AudioDecoder
print('解码成功', AudioDecoder('$EX').metadata.sample_rate)"
```

> **为什么必须用 `env` 传递变量**：macOS 的系统完整性保护（SIP）在启动系统自带的程序（`/bin/bash`、`nohup` 等）时，会清掉所有 `DYLD_*` 开头的环境变量。只用 `export` 的话，变量传不到 Python 进程，就会报 `Could not load libtorchcodec`。`infra/f5/f5.sh` 已经处理了这个问题，你只有在手动运行时才需要注意。

### 6.4 下载模型权重

```bash
cd "$F5_HOME"
.venv/bin/python -m pip install -U "huggingface_hub[cli]" $PIP

export HF_ENDPOINT=https://hf-mirror.com          # 国内镜像；海外不用设
.venv/bin/hf download SWivid/F5-TTS --include "F5TTS_v1_Base/*" --local-dir ./ckpts
```

只下载 `F5TTS_v1_Base` 这一套（约 1.3GB）。**不要下载整个仓库**，那会多出 10GB 以上用不到的文件。

下载完成后应该有这两个文件：

```
ckpts/F5TTS_v1_Base/model_1250000.safetensors   (1.3GB)
ckpts/F5TTS_v1_Base/vocab.txt
```

此外，**第一次启动服务时**，F5 会自动下载声码器 `charactr/vocos-mel-24khz`（约 50MB），存到 `~/.cache/huggingface/hub/`。`f5.sh` 已经默认设置了 `HF_ENDPOINT=https://hf-mirror.com`。

### 6.5 启动服务并测试

```bash
cd ~/Documents/LLMWorkSpace/EchoAgent/echo-agent

make f5                                   # 等价于 ./infra/f5/f5.sh start
./infra/f5/f5.sh say "你好，这是一段测试语音。"   # 合成并直接播放
./infra/f5/f5.sh status
make f5-stop
```

第一次启动要加载模型（约 15 秒），之后合成每句话需要 5～10 秒。

**服务接口**（`infra/f5/f5_server.py`）：

| 接口 | 说明 |
|---|---|
| `GET /health` | 返回 `ok` |
| `POST /tts` | JSON：`text`（必填）、`ref`（参考音频路径）、`ref_text`（参考音频的原文）、`speed`，返回 wav 文件 |

> **安全**：服务只监听 `127.0.0.1`。`ref` 参数可以指向本机任意文件，**绝不能**把它改成监听 `0.0.0.0` 暴露到局域网或外网。

**验证**：

```bash
curl -s http://127.0.0.1:8765/health                 # ok
curl -s http://127.0.0.1:8000/api/health             # 后端启动后，"tts": true
```

---

## 7. Ollama + Qwen3.5-4B（聊天）

只有"聊天"页面需要。不装它，其他功能（配音、写稿）照常可用。

### 7.1 安装 Ollama

使用命令行版本，直接解压到 `LLMWorkSpace/Ollama/bin`，不安装到 `/Applications`，也不会开机自动启动：

```bash
export OLLAMA_HOME=~/Documents/LLMWorkSpace/Ollama
mkdir -p "$OLLAMA_HOME"/{bin,models,logs} && cd "$OLLAMA_HOME"

VER=v0.40.18     # 最新版本号见 https://github.com/ollama/ollama/releases
# 国内用 gh-proxy；海外把前缀 https://gh-proxy.com/ 去掉
curl -fL --http1.1 --retry 5 -C - -o ollama-darwin.tgz \
  "https://gh-proxy.com/https://github.com/ollama/ollama/releases/download/$VER/ollama-darwin.tgz"
```

**核对校验值**（从镜像下载的程序文件一定要做）：

```bash
# 从官方 API 获取 SHA256
curl -s "https://api.github.com/repos/ollama/ollama/releases/tags/$VER" | python3 -c \
  "import sys,json; [print(a['digest']) for a in json.load(sys.stdin)['assets'] if a['name']=='ollama-darwin.tgz']"
shasum -a 256 ollama-darwin.tgz      # 两个值必须一致
```

确认一致后解压：

```bash
tar -xzf ollama-darwin.tgz -C bin && rm ollama-darwin.tgz
bin/ollama --version
```

> 直接从 GitHub 下载时，曾经遇到 90 秒内一个字节都没收到、HTTP/2 报错的情况。所以上面的命令加了 `--http1.1`、`--retry` 和 `-C -`（断点续传）。

### 7.2 下载 Qwen3.5-4B

```bash
cd ~/Documents/LLMWorkSpace/EchoAgent/echo-agent
make ollama          # 启动 Ollama 服务（后台运行，模型目录指向 LLMWorkSpace/Ollama/models）
make ollama-pull     # 下载 qwen3.5:4b，约 3.7GB
```

> **注意**：一定要通过 `make ollama` 启动，它会设置 `OLLAMA_MODELS` 指向 `LLMWorkSpace/Ollama/models`。如果直接运行 `ollama serve`，模型会被下载到 `~/.ollama/models`。

Ollama 的模型仓库在国内没有可靠的镜像，直连速度一般在 0.5～2MB/s，下载 3.7GB 可能要 30 分钟到 1 小时以上。中途断了，再运行一次 `make ollama-pull` 会接着下载。

**验证**：

```bash
OLLAMA_MODELS=~/Documents/LLMWorkSpace/Ollama/models ~/Documents/LLMWorkSpace/Ollama/bin/ollama list   # 能看到 qwen3.5:4b
curl -s http://127.0.0.1:11434/api/chat -d '{
  "model": "qwen3.5:4b", "think": false, "stream": false,
  "messages": [{"role": "user", "content": "用一句话介绍你自己"}]}' | python3 -c "import sys,json; print(json.load(sys.stdin)['message']['content'])"
```

> `"think": false` 用来关闭 Qwen3.5 的思考模式，回复会快很多。这个参数只有 Ollama 原生的 `/api/chat` 接口支持，OpenAI 兼容接口（`/v1/chat/completions`）会忽略它。

**想换模型**：改 `server/.env` 里的 `CHAT_MODEL`，然后运行 `make ollama-pull CHAT_MODEL=新模型名`。内存足够的话，`qwen3.5:9b`（约 6.6GB）的效果明显更好。

---

## 8. 中文参考音色

不配置的话，系统只有 F5 自带的**英文**示例音色，合成中文时会带外国口音。

### 8.1 录音要求

- 安静的房间，手机距离嘴巴 20 厘米左右
- 用平常说话的语速，**5～10 秒**
- 前后各留半秒静音
- **只能用你本人的声音，或者已经取得授权的声音**。克隆他人声音（尤其是公众人物）需要本人同意，这也是《互联网信息服务深度合成管理规定》的要求

参考稿（也可以念别的，记下实际念的原文就行）：

> 大家好，欢迎来到回音。今天天气很好，我们一起轻松地聊聊天吧。

### 8.2 转成标准格式

```bash
mkdir -p ~/Documents/LLMWorkSpace/F5-TTS/voices
ffmpeg -i 你的录音.m4a -ac 1 -ar 24000 ~/Documents/LLMWorkSpace/F5-TTS/voices/my_voice.wav
```

需要截取其中一段的话，加上 `-ss 开始秒数 -to 结束秒数`。

### 8.3 注册为系统音色

```bash
cd ~/Documents/LLMWorkSpace/EchoAgent/echo-agent/server
uv run python -m app.cli add-voice \
  --name "我的声音" \
  --audio ~/Documents/LLMWorkSpace/F5-TTS/voices/my_voice.wav \
  --text "大家好，欢迎来到回音。今天天气很好，我们一起轻松地聊聊天吧。" \
  --tags 温和,中文
```

`--text` 必须和录音内容**逐字一致**，不一致时合成会出现吞字、重复读等问题。

也可以在网页的"账户"页上传，效果一样，但上传的音色只有你自己的账号能用。

---

## 9. 可选组件

### 9.1 Whisper（质检功能）

质检功能会把合成出来的语音转回文字，标出可能读错的句子。默认是关闭的。

```bash
cd ~/Documents/LLMWorkSpace/EchoAgent/echo-agent/server
uv add mlx-whisper                # Apple GPU 上运行 Whisper
# 在 server/.env 里设置：VERIFY_ENABLED=true
```

模型会在第一次使用时自动下载（约 1.6GB）。国内网络请先 `export HF_ENDPOINT=https://hf-mirror.com`。

### 9.2 Claude API（"说需求，AI 写稿"模式）

在 `server/.env` 里填写：

```
ANTHROPIC_API_KEY=你的key
```

> ⚠️ **已知问题**：目前 `.env` 里的这个值**不会生效**。SDK 只读取系统环境变量，而 `.env` 的内容没有传给它，这个 bug 还没修。临时办法是启动前在终端里 `export ANTHROPIC_API_KEY=...`。另外，如果你的环境里设置了 `ANTHROPIC_BASE_URL`（代理网关），请确认 key 对这个网关有效。

不配置也没关系，"我有文案，直接配音"模式和聊天功能都不需要 Claude。

### 9.3 Postgres + Redis（上线、多进程部署时才需要）

本地开发默认用 SQLite，任务在后端进程里执行，不需要这两个。要切换的话：

```bash
# 需要先安装 Docker Desktop 或 OrbStack（https://orbstack.dev）
make deps        # 启动 Postgres 17 + Redis 7（infra/docker-compose.yml）
```

然后修改 `server/.env`：

```
DATABASE_URL=postgresql+asyncpg://echo:echo@127.0.0.1:5432/echo
REDIS_URL=redis://127.0.0.1:6379/0
```

再运行 `make migrate`，并且多开一个终端运行 `make worker`。

---

## 10. 启动、关闭、检查

```bash
cd ~/Documents/LLMWorkSpace/EchoAgent/echo-agent

make doctor     # 检查所有依赖，缺什么提示看本文哪一节
make start      # 后台启动全部服务：ollama → f5 → api → web
make status     # 查看哪些服务在运行
make stop       # 全部关闭
```

启动后打开 http://localhost:3000，注册账号（赠送 300 额度），然后：

- **创作**：贴一段文案，选择音色，生成配音
- **聊天**：http://localhost:3000/chat，用中文或英文聊天，回复会被朗读出来

日志位置：

| 服务 | 日志 |
|---|---|
| 后端 | `logs/api.log` |
| 前端 | `logs/web.log` |
| F5 | `~/Documents/LLMWorkSpace/F5-TTS/f5.log` |
| Ollama | `~/Documents/LLMWorkSpace/Ollama/logs/ollama.log` |

想在前台看实时日志的话，可以不用 `make start`，而是分别开终端运行 `make api`、`make web`（F5 和 Ollama 仍然用 `make f5`、`make ollama` 在后台启动）。

---

## 11. 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `pip install` 报 `PyTorch>=2.6 required` 或 `numpy has no attribute long` | Python 是 Intel 版，PyTorch 被限制在 2.2 | 按 2.1 节装 arm64 版 Python，删掉 `.venv` 重新创建 |
| `MPS: False` | 同上 | 同上 |
| pip 卡在 `Building wheel for llvmlite` | 在从源码编译 | 加上 `--only-binary=:all:` |
| F5 报 `Could not load libtorchcodec` / `Library not loaded: libavutil` | 没找到 FFmpeg 动态库 | 检查 6.3 节的软链接；手动运行时要用 `env DYLD_FALLBACK_LIBRARY_PATH=... python`，不能只 `export` |
| F5 第一次启动卡住 | 正在从 Hugging Face 下载声码器 | 确认 `HF_ENDPOINT=https://hf-mirror.com`；查看 `f5.log` |
| Hugging Face 下载到一半，留下 `.incomplete` 文件 | 网络中断 | 重新运行同一条 `hf download` 命令。残留的 `.incomplete` 文件可以删掉 |
| 合成的中文带外国口音 | 用的是英文示例音色 | 第 8 节 |
| 吞字、重复读 | 参考音频的 `--text` 和实际录音不一致 | 逐字核对 |
| 聊天提示"连不上 Ollama" | Ollama 没启动 | `make ollama` |
| 聊天提示"本地没有模型" | 模型没下载 | `make ollama-pull` |
| 模型下载到了 `~/.ollama` | 没有通过 `make ollama` 启动 | `make ollama-stop`，再用 `make ollama` 启动 |
| `make` 报 `uv: command not found` | uv 不在 PATH | 2.2 节 |
| 端口被占用 | 上次没关干净，或者其他程序占用了端口 | `make status` 查看；`make stop` 只会关闭 EchoAgent 自己的进程 |
| 改了 `next.config.ts` 不生效 | 开发服务器不会重新加载这个文件 | `./scripts/stop.sh web && make start` |
| 安装 Homebrew 卡在 portable-ruby | 国内访问 ghcr.io 不稳定 | 不依赖 Homebrew：按本文的直接下载方式安装 |
