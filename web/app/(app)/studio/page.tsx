"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Button, Card, ErrorText } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { CHARS_PER_SECOND, countUnits } from "@/lib/format";
import { useVoices } from "@/lib/hooks";
import { CreateJobSchema, type CreateJobInput, type Job } from "@/lib/schemas";

const PLACEHOLDER = {
  brief: "例如：帮我写一条 60 秒的口播，介绍一款适合上班族的便携咖啡机，主打三分钟出杯、好清洗，语气轻松一点。",
  script: "把写好的文案粘贴在这里。每句话以句号、问号或感叹号结尾，系统会自动分句、处理数字读法并配音。",
};

export default function StudioPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const { data: voices } = useVoices();
  const [playing, setPlaying] = useState<string | null>(null);
  const sample = useRef<HTMLAudioElement | null>(null);

  const {
    register,
    handleSubmit,
    setValue,
    control,
    formState: { errors },
  } = useForm<CreateJobInput>({
    resolver: zodResolver(CreateJobSchema),
    defaultValues: { mode: "brief", text: "", speed: 1, target_seconds: 60 },
  });
  const [mode, text, speed, voiceId] = useWatch({ control, name: ["mode", "text", "speed", "voice_id"] });

  const create = useMutation({
    mutationFn: (body: CreateJobInput) => api.post<Job>("/api/jobs", body),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ["me"] });
      router.push(`/jobs/${job.id}`);
    },
  });

  function onSubmit(values: CreateJobInput) {
    create.mutate({
      ...values,
      voice_id: values.voice_id || undefined,
      target_seconds: values.mode === "brief" ? values.target_seconds : undefined,
    });
  }

  function toggleSample(id: string) {
    sample.current?.pause();
    if (playing === id) return setPlaying(null);
    const audio = new Audio(`/api/voices/${id}/sample`);
    audio.onended = () => setPlaying(null);
    void audio.play();
    sample.current = audio;
    setPlaying(id);
  }

  const estSeconds = mode === "script" ? countUnits(text ?? "") / (CHARS_PER_SECOND * (speed || 1)) : null;

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-6 md:grid-cols-[1fr_300px]">
      <Card>
        <div className="flex gap-2">
          {(["brief", "script"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setValue("mode", m, { shouldValidate: false })}
              className={`rounded-lg px-4 py-2 text-sm ${mode === m ? "bg-blue-600 text-white" : "bg-zinc-100 text-zinc-700"}`}
            >
              {m === "brief" ? "说需求，AI 写稿" : "我有文案，直接配音"}
            </button>
          ))}
        </div>

        <textarea
          {...register("text")}
          rows={12}
          placeholder={PLACEHOLDER[mode]}
          className="mt-4 w-full resize-y rounded-lg border border-zinc-300 p-3 leading-relaxed"
        />
        <ErrorText>{errors.text?.message}</ErrorText>

        <div className="mt-2 flex justify-between text-sm text-zinc-500">
          <span>{countUnits(text ?? "")} 字</span>
          {estSeconds !== null && <span>预计时长约 {Math.round(estSeconds)} 秒</span>}
        </div>

        <ErrorText>{create.error instanceof ApiError ? create.error.message : create.error?.message}</ErrorText>
        <Button type="submit" disabled={create.isPending} className="mt-4 w-full py-3">
          {create.isPending ? "提交中…" : mode === "brief" ? "开始生成" : "开始配音"}
        </Button>
      </Card>

      <div className="space-y-6">
        <Card>
          <h2 className="font-medium">音色</h2>
          {mode === "brief" && <p className="mt-1 text-xs text-zinc-500">不选的话，AI 会按内容风格自动挑选</p>}
          <div className="mt-3 space-y-2">
            {mode === "brief" && (
              <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-200 p-2 text-sm">
                <input type="radio" value="" {...register("voice_id")} />
                让 AI 选
              </label>
            )}
            {voices?.map((v) => (
              <label
                key={v.id}
                className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2 text-sm ${
                  voiceId === v.id ? "border-blue-500 bg-blue-50" : "border-zinc-200"
                }`}
              >
                <input type="radio" value={v.id} {...register("voice_id")} className="mt-1" />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{v.name}</span>
                  {v.is_mine && <span className="ml-1 text-xs text-blue-600">我的</span>}
                  <span className="block truncate text-xs text-zinc-500">{v.tags.join(" · ")}</span>
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    toggleSample(v.id);
                  }}
                  className="text-xs text-blue-600"
                >
                  {playing === v.id ? "停止" : "试听"}
                </button>
              </label>
            ))}
            {voices?.length === 0 && (
              <p className="text-sm text-zinc-500">还没有音色，请先在后端执行 seed-voices，或在账户页上传。</p>
            )}
          </div>
          <ErrorText>{errors.voice_id?.message}</ErrorText>
        </Card>

        <Card className="space-y-4">
          {mode === "brief" && (
            <div>
              <label className="text-sm font-medium">目标时长（秒）</label>
              <input
                type="number"
                {...register("target_seconds", { valueAsNumber: true })}
                className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2"
              />
              <ErrorText>{errors.target_seconds?.message}</ErrorText>
            </div>
          )}
          <div>
            <label className="text-sm font-medium">语速 {speed?.toFixed(1)}x</label>
            <input
              type="range"
              min={0.7}
              max={1.5}
              step={0.1}
              {...register("speed", { valueAsNumber: true })}
              className="mt-2 w-full"
            />
            {mode === "brief" && <p className="text-xs text-zinc-500">AI 可能会根据内容微调</p>}
          </div>
        </Card>
      </div>
    </form>
  );
}
