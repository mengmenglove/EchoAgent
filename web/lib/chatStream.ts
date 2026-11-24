// 发一条聊天消息，并读取后端返回的 SSE 流。
//
// 为什么不用 EventSource：EventSource 只能发 GET，而这里要 POST 消息内容。
// 所以用 fetch 拿到响应体的 ReadableStream，自己按 SSE 格式（空行分隔，每段 event: / data:）解析。
import { ApiError } from "./api";

export type ChatEvent =
  | { type: "user_saved"; id: number }
  | { type: "delta"; text: string }
  | { type: "text_done"; id: number; text: string }
  | { type: "audio"; id: number; audio_ms: number }
  | { type: "audio_progress"; done: number; total: number }
  | { type: "ping" }
  | { type: "error" | "audio_error"; message: string }
  | { type: "done" };

export async function sendChat(
  sessionId: string,
  body: { text: string; speak: boolean },
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, data?.error?.code ?? "http_error", data?.error?.message ?? "发送失败");
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    // 一个事件以空行结束；最后一段可能还没收全，留在 buf 里等下次
    const blocks = buf.split("\n\n");
    buf = blocks.pop() ?? "";
    for (const block of blocks) {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ type: event, ...JSON.parse(data) } as ChatEvent);
    }
  }
}

export const audioUrl = (sessionId: string, messageId: number) =>
  `/api/chat/sessions/${sessionId}/messages/${messageId}/audio`;
