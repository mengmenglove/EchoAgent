#!/usr/bin/env python3
"""F5-TTS 常驻 HTTP 服务（EchoAgent 用）。模型只加载一次，之后每次合成走 HTTP。

接口（server/app/tts/f5.py 按这个格式调用）：
  GET  /health  -> 200 ok
  POST /tts     JSON {"text", "ref", "ref_text", "speed", "out"} -> audio/wav 二进制
    text      要合成的文字（必填）
    ref       参考音频路径（本机可读的 wav）；不填用 F5 自带的英文示例
    ref_text  参考音频里念的原文；不填则自动转写（需要 Whisper，较慢）
    speed     语速，默认 1.0
    out       忽略（为兼容旧客户端保留）；结果直接在响应里返回，不在磁盘留文件

环境变量：
  F5_CKPT   模型权重 .safetensors 路径（必填）
  F5_VOCAB  vocab.txt 路径（必填）
  F5_HOST   默认 127.0.0.1。不要改成 0.0.0.0：ref 可以指向任意本地文件，绝不能暴露到外网
  F5_PORT   默认 8765
"""

import json
import os
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

HOST = os.environ.get("F5_HOST", "127.0.0.1")
PORT = int(os.environ.get("F5_PORT", "8765"))
CKPT = os.environ["F5_CKPT"]
VOCAB = os.environ["F5_VOCAB"]

DEFAULT_REF = str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav"))
DEFAULT_REF_TEXT = "Some call me nature, others call me mother nature."

print("[f5] 正在加载模型（只需一次，约十几秒）...", flush=True)
from f5_tts.api import F5TTS

MODEL = F5TTS(model="F5TTS_v1_Base", ckpt_file=CKPT, vocab_file=VOCAB)
LOCK = threading.Lock()  # 模型对象不是线程安全的，一次只合成一句
print(f"[f5] 模型加载完成，device={MODEL.device}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, b"ok")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        if self.path != "/tts":
            self._send(404, b"not found")
            return
        try:
            req = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}"
            )
            text = (req.get("text") or "").strip()
            if not text:
                self._send(400, b"missing 'text'")
                return
            ref = req.get("ref") or DEFAULT_REF
            ref_text = req.get("ref_text")
            if ref_text is None:
                ref_text = DEFAULT_REF_TEXT if ref == DEFAULT_REF else ""
            if not os.path.isfile(ref):
                self._send(400, f"ref not found: {ref}".encode())
                return
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp, LOCK:
                print(f"[f5] 合成: {text[:40]}", flush=True)
                MODEL.infer(
                    ref_file=ref,
                    ref_text=ref_text,
                    gen_text=text,
                    speed=float(req.get("speed", 1.0)),
                    file_wave=tmp.name,
                )
                with open(tmp.name, "rb") as f:
                    data = f.read()
            self._send(200, data, "audio/wav")
        except Exception as e:
            traceback.print_exc()
            self._send(500, f"error: {e}".encode())


if __name__ == "__main__":
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[f5] 就绪 http://{HOST}:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
