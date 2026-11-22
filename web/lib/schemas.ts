// 与后端 server/app/schemas.py 一一对应。前端校验是为了体验，后端校验才是为了安全。
import { z } from "zod";

export const CreateJobSchema = z
  .object({
    mode: z.enum(["script", "brief"]),
    text: z.string().trim().min(1, "请输入内容").max(5000, "最多 5000 字"),
    target_seconds: z.number().int().min(5).max(600).optional(),
    voice_id: z.string().optional(),
    speed: z.number().min(0.7).max(1.5),
  })
  .refine((v) => v.mode === "brief" || !!v.voice_id, {
    message: "文案直出模式必须选择音色",
    path: ["voice_id"],
  });

export type CreateJobInput = z.infer<typeof CreateJobSchema>;

export const AuthSchema = z.object({
  email: z.email("邮箱格式不正确"),
  password: z.string().min(8, "密码至少 8 位").max(128),
});

export type AuthInput = z.infer<typeof AuthSchema>;

export type Segment = { text: string; pause_ms: number };

export type JobStatus =
  | "queued"
  | "writing"
  | "needs_input"
  | "synthesizing"
  | "verifying"
  | "succeeded"
  | "failed"
  | "canceled";

export const TERMINAL: JobStatus[] = ["succeeded", "failed", "canceled"];

export type Job = {
  id: string;
  parent_id: string | null;
  mode: "script" | "brief";
  status: JobStatus;
  title: string;
  input_text: string;
  script: Segment[] | null;
  voice_id: string | null;
  speed: number;
  target_seconds: number | null;
  duration_ms: number | null;
  spans: [number, number][] | null;
  verify_report: { index: number; heard: string; cer: number; flag: boolean }[] | null;
  error: string | null;
  pending_questions: string[] | null;
  credits_held: number;
  credits_charged: number;
  has_audio: boolean;
  created_at: string;
  updated_at: string;
};

export type JobEvent = { id: number; type: string; payload: Record<string, unknown> };

export type User = { id: string; email: string; credits_balance: number; created_at: string };

export type Voice = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  language: string;
  is_mine: boolean;
};

export type LedgerEntry = {
  id: number;
  delta: number;
  reason: string;
  job_id: string | null;
  note: string;
  created_at: string;
};
