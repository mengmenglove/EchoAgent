"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AudioPlayer, type PlayerHandle } from "@/components/AudioPlayer";
import { Button, Card, ErrorText, Spinner, StatusBadge } from "@/components/ui";
import { api, ApiError, fileUrl } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { useJob, useJobEvents } from "@/lib/hooks";
import { TERMINAL, type Job, type JobEvent, type Segment } from "@/lib/schemas";

const STEPS = [
  { key: "writing", label: "写稿" },
  { key: "synthesizing", label: "合成" },
  { key: "done", label: "完成" },
] as const;

function stepIndex(job: Job): number {
  if (job.status === "succeeded") return 3;
  if (job.status === "synthesizing" || job.status === "verifying") return 1;
  return 0;
}

function describe(ev: JobEvent): string | null {
  const p = ev.payload as Record<string, unknown>;
  switch (ev.type) {
    case "created":
      return `已提交，预扣 ${p.credits_held} 额度`;
    case "agent_step":
      return String(p.summary);
    case "agent_note":
      return `AI：${String(p.text)}`;
    case "script_ready":
      return `文案完成：《${p.title}》`;
    case "question":
      return "AI 有问题想问你";
    case "answered":
      return `你回答了：${p.answer}`;
    case "tts_segment_done":
      return `合成第 ${Number(p.index) + 1}/${p.total} 句${p.cached ? "（缓存）" : ""}`;
    case "verified":
      return `质检完成：${p.flagged} 句可能读错`;
    case "succeeded":
      return `完成，实际消耗 ${p.credits_charged} 额度`;
    case "failed":
      return `失败：${p.error}`;
    case "canceled":
      return "已取消，额度已退回";
    default:
      return null;
  }
}

export function JobDetail({ id }: { id: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: job, error } = useJob(id);
  const running = !!job && !TERMINAL.includes(job.status);
  const events = useJobEvents(id, running);
  const player = useRef<PlayerHandle>(null);
  const [currentMs, setCurrentMs] = useState(0);
  const [editing, setEditing] = useState<Segment[] | null>(null);
  const [answer, setAnswer] = useState("");

  const refresh = () => qc.invalidateQueries({ queryKey: ["job", id] });
  const cancel = useMutation({ mutationFn: () => api.post(`/api/jobs/${id}/cancel`), onSuccess: refresh });
  const reply = useMutation({
    mutationFn: () => api.post(`/api/jobs/${id}/answer`, { answer }),
    onSuccess: () => {
      setAnswer("");
      refresh();
    },
  });
  const revise = useMutation({
    mutationFn: (segments: Segment[]) => api.post<Job>(`/api/jobs/${id}/revise`, { segments }),
    onSuccess: (child) => router.push(`/jobs/${child.id}`),
  });

  // 播放到哪一句：用当前时间去字幕时间轴里找。
  // 不用手写 useMemo：项目开启了 React Compiler，它会自动做记忆化，手写的反而会和它冲突。
  const activeIndex = job?.spans?.findIndex(([s, e]) => currentMs >= s && currentMs < e) ?? -1;

  if (error) return <p className="text-red-600">{(error as Error).message}</p>;
  if (!job) return <Spinner />;

  const segmentTotal = events.filter((e) => e.type === "tts_segment_done").at(-1)?.payload.total as number | undefined;
  const segmentDone = events.filter((e) => e.type === "tts_segment_done").length;
  const timeline = events.map((e) => ({ id: e.id, text: describe(e) })).filter((e) => e.text);
  const flagged = new Set(job.verify_report?.filter((r) => r.flag).map((r) => r.index));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{job.title || "未命名"}</h1>
        <StatusBadge status={job.status} />
        <span className="text-sm text-zinc-500">{formatTime(job.created_at)}</span>
        {job.parent_id && (
          <Link href={`/jobs/${job.parent_id}`} className="text-sm text-blue-600">
            ← 来源版本
          </Link>
        )}
        {running && (
          <Button variant="danger" className="ml-auto" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            取消
          </Button>
        )}
      </div>

      {running && (
        <Card>
          <ol className="flex items-center gap-2 text-sm">
            {STEPS.filter((s) => job.mode === "brief" || s.key !== "writing").map((s, i, arr) => {
              const idx = job.mode === "brief" ? i : i + 1;
              const cur = stepIndex(job);
              return (
                <li key={s.key} className="flex items-center gap-2">
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                      idx < cur ? "bg-blue-600 text-white" : idx === cur ? "bg-blue-100 text-blue-700" : "bg-zinc-100 text-zinc-400"
                    }`}
                  >
                    {idx === cur && job.status !== "needs_input" ? <Spinner /> : i + 1}
                  </span>
                  <span className={idx === cur ? "font-medium" : "text-zinc-500"}>{s.label}</span>
                  {i < arr.length - 1 && <span className="mx-2 h-px w-10 bg-zinc-200" />}
                </li>
              );
            })}
          </ol>
          {job.status === "synthesizing" && segmentTotal && (
            <div className="mt-4">
              <div className="h-2 overflow-hidden rounded bg-zinc-100">
                <div className="h-full bg-blue-600 transition-all" style={{ width: `${(segmentDone / segmentTotal) * 100}%` }} />
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {segmentDone}/{segmentTotal} 句
              </p>
            </div>
          )}
        </Card>
      )}

      {job.status === "needs_input" && job.pending_questions && (
        <Card className="border-amber-300 bg-amber-50">
          <h2 className="font-medium">AI 需要你补充一些信息</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {job.pending_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={3}
            className="mt-3 w-full rounded-lg border border-amber-300 bg-white p-2"
            placeholder="在这里回答，可以一次回答所有问题"
          />
          <Button onClick={() => reply.mutate()} disabled={!answer.trim() || reply.isPending} className="mt-2">
            提交回答
          </Button>
        </Card>
      )}

      {job.status === "failed" && <Card className="border-red-200 bg-red-50 text-red-700">{job.error}</Card>}

      {job.has_audio && (
        <Card className="space-y-4">
          <AudioPlayer ref={player} url={fileUrl(job.id, "mp3")} onTime={setCurrentMs} />
          <div className="flex flex-wrap gap-2 text-sm">
            <span className="mr-auto text-zinc-500">
              时长 {formatDuration(job.duration_ms)} · 消耗 {job.credits_charged} 额度
            </span>
            {(["mp3", "wav", "srt"] as const).map((f) => (
              <a key={f} href={fileUrl(job.id, f, true)} className="rounded-lg border border-zinc-300 px-3 py-1.5 hover:bg-zinc-50">
                下载 {f.toUpperCase()}
              </a>
            ))}
          </div>
        </Card>
      )}

      {job.script && (
        <Card>
          <div className="mb-3 flex items-center">
            <h2 className="font-medium">文案</h2>
            {job.status === "succeeded" && !editing && (
              <Button variant="secondary" className="ml-auto" onClick={() => setEditing(job.script!.map((s) => ({ ...s })))}>
                改稿重新生成
              </Button>
            )}
          </div>

          {editing ? (
            <div className="space-y-2">
              {editing.map((s, i) => (
                <textarea
                  key={i}
                  value={s.text}
                  rows={1}
                  onChange={(e) => setEditing(editing.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                  className="w-full resize-y rounded-lg border border-zinc-300 p-2"
                />
              ))}
              <p className="text-xs text-zinc-500">没改动的句子会直接复用之前的合成结果，几乎不花时间。</p>
              <ErrorText>{revise.error instanceof ApiError ? revise.error.message : null}</ErrorText>
              <div className="flex gap-2">
                <Button onClick={() => revise.mutate(editing.filter((s) => s.text.trim()))} disabled={revise.isPending}>
                  生成新版本
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>
                  取消
                </Button>
              </div>
            </div>
          ) : (
            <ol className="space-y-1">
              {job.script.map((s, i) => (
                <li key={i}>
                  <button
                    type="button"
                    disabled={!job.spans}
                    onClick={() => {
                      if (job.spans?.[i]) {
                        player.current?.seek(job.spans[i][0]);
                        player.current?.play();
                      }
                    }}
                    className={`w-full rounded-md px-2 py-1 text-left leading-relaxed ${
                      i === activeIndex ? "bg-blue-100" : job.spans ? "hover:bg-zinc-50" : ""
                    }`}
                  >
                    {s.text}
                    {flagged.has(i) && (
                      <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-800">
                        可能读错：{job.verify_report?.find((r) => r.index === i)?.heard}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}

      {timeline.length > 0 && (
        <Card>
          <h2 className="mb-2 font-medium">过程</h2>
          <ul className="space-y-1 text-sm text-zinc-600">
            {timeline.map((e) => (
              <li key={e.id}>· {e.text}</li>
            ))}
          </ul>
        </Card>
      )}

      {job.mode === "brief" && (
        <details className="text-sm text-zinc-500">
          <summary className="cursor-pointer">原始需求</summary>
          <p className="mt-2 whitespace-pre-wrap">{job.input_text}</p>
        </details>
      )}
    </div>
  );
}
