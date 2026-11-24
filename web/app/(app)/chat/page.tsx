"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button, Card, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { audioUrl, sendChat, type ChatEvent } from "@/lib/chatStream";
import { useVoices } from "@/lib/hooks";
import type { ChatMessage, ChatSession } from "@/lib/schemas";

type Pending = { user: string; reply: string; stage: "thinking" | "writing" | "speaking"; audio?: string };

export default function ChatPage() {
  const qc = useQueryClient();
  const { data: voices } = useVoices();
  const { data: sessions } = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => api.get<ChatSession[]>("/api/chat/sessions"),
  });
  const [activeId, setActiveId] = useState<string | null>(null);
  const sessionId = activeId ?? sessions?.[0]?.id ?? null;
  const session = sessions?.find((s) => s.id === sessionId);

  const { data: messages } = useQuery({
    queryKey: ["chat-messages", sessionId],
    queryFn: () => api.get<ChatMessage[]>(`/api/chat/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
  });

  const [input, setInput] = useState("");
  const [speak, setSpeak] = useState(true);
  const [pending, setPending] = useState<Pending | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 新消息出来时滚到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages?.length, pending?.reply]);

  // 离开页面时停止播放、断开正在进行的请求
  useEffect(
    () => () => {
      audioRef.current?.pause();
      abortRef.current?.abort();
    },
    [],
  );

  const newSession = useMutation({
    mutationFn: () => api.post<ChatSession>("/api/chat/sessions", { voice_id: session?.voice_id ?? undefined }),
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      setActiveId(s.id);
    },
  });

  const changeVoice = useMutation({
    mutationFn: (voice_id: string) => api.patch(`/api/chat/sessions/${sessionId}`, { voice_id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-sessions"] }),
  });

  const removeSession = useMutation({
    mutationFn: (id: string) => api.del(`/api/chat/sessions/${id}`),
    onSuccess: () => {
      setActiveId(null);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });

  function play(messageId: number) {
    if (!sessionId) return;
    audioRef.current?.pause();
    if (playingId === messageId) return setPlayingId(null);
    const a = new Audio(audioUrl(sessionId, messageId));
    a.onended = () => setPlayingId(null);
    void a.play().catch(() => setPlayingId(null)); // 浏览器可能拦截自动播放
    audioRef.current = a;
    setPlayingId(messageId);
  }

  async function send() {
    const text = input.trim();
    if (!text || pending) return;
    let sid = sessionId;
    if (!sid) {
      const s = await api.post<ChatSession>("/api/chat/sessions", {});
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
      setActiveId(s.id);
      sid = s.id;
    }
    setInput("");
    setError(null);
    setPending({ user: text, reply: "", stage: "thinking" });
    abortRef.current = new AbortController();

    const onEvent = (e: ChatEvent) => {
      switch (e.type) {
        case "delta":
          setPending((p) => p && { ...p, reply: p.reply + e.text, stage: "writing" });
          break;
        case "text_done":
          setPending((p) => p && { ...p, reply: e.text, stage: speak ? "speaking" : "writing" });
          break;
        case "audio_progress":
          setPending((p) => p && { ...p, audio: `${e.done}/${e.total}` });
          break;
        case "audio":
          play(e.id); // 语音合成好了，自动播放
          break;
        case "error":
        case "audio_error":
          setError(e.message);
          break;
      }
    };

    try {
      await sendChat(sid, { text, speak }, onEvent, abortRef.current.signal);
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setError(e instanceof ApiError ? e.message : String(e));
      }
    } finally {
      setPending(null);
      await qc.invalidateQueries({ queryKey: ["chat-messages", sid] });
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    }
  }

  return (
    <div className="grid h-[calc(100vh-8rem)] gap-4 md:grid-cols-[220px_1fr]">
      <aside className="hidden flex-col gap-2 overflow-y-auto md:flex">
        <Button onClick={() => newSession.mutate()} disabled={newSession.isPending}>
          + 新对话
        </Button>
        {sessions?.map((s) => (
          <div
            key={s.id}
            className={`group flex items-center rounded-lg px-3 py-2 text-sm ${
              s.id === sessionId ? "bg-zinc-200 font-medium" : "hover:bg-zinc-100"
            }`}
          >
            <button className="min-w-0 flex-1 truncate text-left" onClick={() => setActiveId(s.id)}>
              {s.title}
            </button>
            <button
              onClick={() => confirm("删除这段对话？") && removeSession.mutate(s.id)}
              className="ml-1 hidden text-zinc-400 hover:text-red-600 group-hover:block"
              aria-label="删除"
            >
              ×
            </button>
          </div>
        ))}
      </aside>

      <Card className="flex min-h-0 flex-col p-0">
        <div className="flex items-center gap-3 border-b border-zinc-200 px-4 py-3 text-sm">
          <span className="font-medium">语音聊天</span>
          <span className="text-zinc-400">本地 Qwen3.5-4B + F5-TTS</span>
          <label className="ml-auto flex items-center gap-1">
            音色
            <select
              value={session?.voice_id ?? ""}
              disabled={!session}
              onChange={(e) => changeVoice.mutate(e.target.value)}
              className="rounded border border-zinc-300 px-2 py-1"
            >
              {voices?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={speak} onChange={(e) => setSpeak(e.target.checked)} />
            朗读回复
          </label>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {!messages?.length && !pending && (
            <p className="mt-20 text-center text-zinc-400">
              用英文或中文随便聊聊，比如 “Hi, can you help me practice English?”
            </p>
          )}
          {messages?.map((m) => (
            <Bubble
              key={m.id}
              role={m.role}
              text={m.content}
              audio={m.has_audio ? { playing: playingId === m.id, onPlay: () => play(m.id) } : undefined}
            />
          ))}
          {pending && (
            <>
              <Bubble role="user" text={pending.user} />
              <Bubble
                role="assistant"
                text={pending.reply}
                status={pending.stage === "thinking" ? "思考中…" : pending.stage === "speaking" ? `正在生成语音…${pending.audio ?? ""}` : undefined}
              />
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {error && <p className="px-4 pb-2 text-sm text-red-600">{error}</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
          className="flex gap-2 border-t border-zinc-200 p-3"
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // 回车发送，Shift+回车换行；输入法选字时的回车不算
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            rows={2}
            placeholder="输入消息，回车发送"
            className="flex-1 resize-none rounded-lg border border-zinc-300 px-3 py-2"
          />
          <Button type="submit" disabled={!input.trim() || !!pending}>
            {pending ? <Spinner /> : "发送"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

function Bubble({
  role,
  text,
  status,
  audio,
}: {
  role: "user" | "assistant";
  text: string;
  status?: string;
  audio?: { playing: boolean; onPlay: () => void };
}) {
  const mine = role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 leading-relaxed ${
          mine ? "bg-blue-600 text-white" : "bg-zinc-100 text-zinc-900"
        }`}
      >
        {text && <p className="whitespace-pre-wrap">{text}</p>}
        {status && (
          <p className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner /> {status}
          </p>
        )}
        {audio && (
          <button onClick={audio.onPlay} className="mt-1 text-sm text-blue-600">
            {audio.playing ? "❚❚ 暂停" : "▶ 播放语音"}
          </button>
        )}
      </div>
    </div>
  );
}
