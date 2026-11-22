import type { JobStatus } from "./schemas";

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "排队中",
  writing: "写稿中",
  needs_input: "等你回答",
  synthesizing: "合成中",
  verifying: "质检中",
  succeeded: "已完成",
  failed: "失败",
  canceled: "已取消",
};

export const STATUS_COLOR: Record<JobStatus, string> = {
  queued: "bg-zinc-100 text-zinc-700",
  writing: "bg-blue-100 text-blue-700",
  needs_input: "bg-amber-100 text-amber-800",
  synthesizing: "bg-blue-100 text-blue-700",
  verifying: "bg-blue-100 text-blue-700",
  succeeded: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
  canceled: "bg-zinc-100 text-zinc-500",
};

export function formatDuration(ms: number | null | undefined): string {
  if (!ms) return "--";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// 与后端 chunker.count_units / CHARS_PER_SECOND 保持一致，用于输入时的实时估算
export function countUnits(text: string): number {
  const cjk = text.match(/[一-鿿]/g)?.length ?? 0;
  const words = text.match(/[A-Za-z]+|\d+(?:\.\d+)?/g)?.length ?? 0;
  return cjk + words;
}

export const CHARS_PER_SECOND = 4.2;
