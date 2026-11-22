"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { TERMINAL, type Job, type JobEvent, type User, type Voice } from "./schemas";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/api/me") });
}

export function useVoices() {
  return useQuery({ queryKey: ["voices"], queryFn: () => api.get<Voice[]>("/api/voices"), staleTime: 60_000 });
}

export function useJob(id: string) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => api.get<Job>(`/api/jobs/${id}`),
    // SSE 是主要的更新方式；这里每 5 秒兜底刷新一次，任务结束后停止
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 5000),
  });
}

/**
 * 订阅任务进度（SSE）。
 *
 * EventSource 断线后会自动重连，并自动带上 Last-Event-ID 请求头，后端据此补发漏掉的事件。
 * 收到状态变化类事件时，让 useJob 的缓存失效、重新拉取详情。
 *
 * cacheComponents 开启后，离开页面时组件不卸载而是隐藏，但 effect 会被清理——
 * 所以连接一定要在清理函数里关闭，回到页面时 effect 重新执行、重新连接。
 */
export function useJobEvents(jobId: string, enabled: boolean) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<JobEvent[]>([]);
  const seen = useRef(new Set<number>());

  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(`/api/jobs/${jobId}/events`, { withCredentials: true });
    es.addEventListener("progress", (msg) => {
      const ev = JSON.parse((msg as MessageEvent<string>).data) as JobEvent;
      if (seen.current.has(ev.id)) return; // 重连时可能重复，按 id 去重
      seen.current.add(ev.id);
      setEvents((prev) => [...prev, ev]);
      if (["status_changed", "script_ready", "question", "succeeded", "failed", "canceled"].includes(ev.type)) {
        qc.invalidateQueries({ queryKey: ["job", jobId] });
      }
      if (["succeeded", "failed", "canceled"].includes(ev.type)) {
        qc.invalidateQueries({ queryKey: ["me"] }); // 余额变了
        es.close();
      }
    });
    return () => es.close();
  }, [jobId, enabled, qc]);

  return events;
}
