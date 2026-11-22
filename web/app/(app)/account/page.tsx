"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, ErrorText } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { useMe, useVoices } from "@/lib/hooks";
import type { LedgerEntry } from "@/lib/schemas";

const REASON: Record<string, string> = {
  signup: "注册赠送",
  topup: "充值",
  hold: "预扣",
  release: "退回预扣",
  charge: "扣费",
};

const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : e ? String(e) : null);

function Credits() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: ledger } = useQuery({
    queryKey: ["ledger"],
    queryFn: () => api.get<LedgerEntry[]>("/api/billing/ledger"),
  });
  const [code, setCode] = useState("");
  const redeem = useMutation({
    mutationFn: () => api.post("/api/billing/redeem", { code }),
    onSuccess: () => {
      setCode("");
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["ledger"] });
    },
  });

  return (
    <Card>
      <h2 className="font-medium">额度</h2>
      <p className="mt-2 text-3xl font-semibold">{me?.credits_balance ?? "--"}</p>
      <p className="text-xs text-zinc-500">1 额度 = 1 秒成品音频；AI 写稿每次另加少量额度</p>
      <div className="mt-4 flex gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="兑换码"
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 uppercase"
        />
        <Button onClick={() => redeem.mutate()} disabled={!code.trim() || redeem.isPending}>
          兑换
        </Button>
      </div>
      <ErrorText>{errMsg(redeem.error)}</ErrorText>
      <table className="mt-4 w-full text-sm">
        <tbody>
          {ledger?.map((l) => (
            <tr key={l.id} className="border-t border-zinc-100">
              <td className="py-1.5 text-zinc-500">{formatTime(l.created_at)}</td>
              <td>{REASON[l.reason] ?? l.reason}</td>
              <td className={`text-right ${l.delta > 0 ? "text-emerald-600" : "text-zinc-800"}`}>
                {l.delta > 0 ? `+${l.delta}` : l.delta}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Voices() {
  const qc = useQueryClient();
  const { data: voices } = useVoices();
  const [form, setForm] = useState({ name: "", ref_text: "", tags: "", consent: false });
  const [file, setFile] = useState<File | null>(null);

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("name", form.name);
      fd.append("ref_text", form.ref_text);
      fd.append("tags", form.tags);
      fd.append("consent", String(form.consent));
      fd.append("file", file!);
      return api.post("/api/voices", fd);
    },
    onSuccess: () => {
      setForm({ name: "", ref_text: "", tags: "", consent: false });
      setFile(null);
      qc.invalidateQueries({ queryKey: ["voices"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/voices/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["voices"] }),
  });

  return (
    <Card>
      <h2 className="font-medium">我的音色</h2>
      <ul className="mt-2 space-y-1 text-sm">
        {voices
          ?.filter((v) => v.is_mine)
          .map((v) => (
            <li key={v.id} className="flex items-center justify-between">
              <span>
                {v.name} <span className="text-zinc-400">{v.tags.join(" · ")}</span>
              </span>
              <button onClick={() => remove.mutate(v.id)} className="text-xs text-red-600">
                删除
              </button>
            </li>
          ))}
      </ul>

      <div className="mt-4 space-y-2 border-t border-zinc-100 pt-4">
        <p className="text-sm text-zinc-600">
          上传一段 3~30 秒、安静环境下的清晰录音，并填写录音里<strong>逐字一致</strong>的原文。
        </p>
        <input type="file" accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
        <input
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="名称，如：我的声音"
          className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm"
        />
        <textarea
          value={form.ref_text}
          onChange={(e) => setForm({ ...form, ref_text: e.target.value })}
          placeholder="录音里念的原文"
          rows={2}
          className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm"
        />
        <input
          value={form.tags}
          onChange={(e) => setForm({ ...form, tags: e.target.value })}
          placeholder="风格标签，逗号分隔，如：温柔,女声"
          className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm"
        />
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.consent}
            onChange={(e) => setForm({ ...form, consent: e.target.checked })}
            className="mt-1"
          />
          我确认这是我本人的声音，或已获得声音本人的授权。
        </label>
        <ErrorText>{errMsg(upload.error)}</ErrorText>
        <Button
          onClick={() => upload.mutate()}
          disabled={!file || !form.name || !form.ref_text || !form.consent || upload.isPending}
        >
          {upload.isPending ? "上传中…" : "上传音色"}
        </Button>
      </div>
    </Card>
  );
}

function Lexicon() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["lexicon"],
    queryFn: () => api.get<Record<string, string>>("/api/me/lexicon"),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? Object.entries(data ?? {}).map(([k, v]) => `${k}=${v}`).join("\n");

  const save = useMutation({
    mutationFn: () => {
      const entries = Object.fromEntries(
        text
          .split("\n")
          .map((l) => l.split("="))
          .filter((p) => p.length === 2 && p[0].trim() && p[1].trim())
          .map(([k, v]) => [k.trim(), v.trim()]),
      );
      return api.put("/api/me/lexicon", { entries });
    },
    onSuccess: () => {
      setDraft(null);
      qc.invalidateQueries({ queryKey: ["lexicon"] });
    },
  });

  return (
    <Card>
      <h2 className="font-medium">读音词典</h2>
      <p className="mt-1 text-sm text-zinc-500">
        合成前自动替换，用来纠正读错的词。每行一条，格式：原词=读法。字幕仍然显示原词。
      </p>
      <textarea
        value={text}
        onChange={(e) => setDraft(e.target.value)}
        rows={6}
        placeholder={"iPhone=爱疯\nApp=A P P"}
        className="mt-3 w-full rounded-lg border border-zinc-300 p-2 font-mono text-sm"
      />
      <ErrorText>{errMsg(save.error)}</ErrorText>
      <Button onClick={() => save.mutate()} disabled={draft === null || save.isPending} className="mt-2">
        保存
      </Button>
    </Card>
  );
}

export default function AccountPage() {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Credits />
      <div className="space-y-6">
        <Voices />
        <Lexicon />
      </div>
    </div>
  );
}
