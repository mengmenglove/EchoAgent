"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Button, Card, Spinner, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDuration, formatTime } from "@/lib/format";
import { TERMINAL, type Job } from "@/lib/schemas";

type Page = { items: Job[]; next_cursor: string | null };

export default function HistoryPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");

  // 游标分页：每页带上上一页返回的 next_cursor
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useInfiniteQuery({
    queryKey: ["jobs", search],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "20" });
      if (pageParam) params.set("cursor", pageParam);
      if (search) params.set("q", search);
      return api.get<Page>(`/api/jobs?${params}`);
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/jobs/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const jobs = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(q.trim());
        }}
        className="flex gap-2"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索标题或内容"
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2"
        />
        <Button type="submit" variant="secondary">
          搜索
        </Button>
      </form>

      {isLoading && <Spinner />}
      {!isLoading && jobs.length === 0 && (
        <Card className="text-center text-zinc-500">
          还没有记录，去 <Link href="/studio" className="text-blue-600">创作</Link> 一条吧
        </Card>
      )}

      <div className="space-y-2">
        {jobs.map((j) => (
          <Card key={j.id} className="flex items-center gap-4 p-4">
            <Link href={`/jobs/${j.id}`} className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">{j.title || "未命名"}</span>
                <StatusBadge status={j.status} />
                {j.parent_id && <span className="text-xs text-zinc-400">改稿版</span>}
              </div>
              <div className="mt-1 text-sm text-zinc-500">
                {j.mode === "brief" ? "AI 写稿" : "文案直出"} · {formatDuration(j.duration_ms)} · {formatTime(j.created_at)}
              </div>
            </Link>
            {TERMINAL.includes(j.status) && (
              <Button
                variant="ghost"
                onClick={() => confirm("确定删除这条记录和音频吗？") && remove.mutate(j.id)}
                disabled={remove.isPending}
              >
                删除
              </Button>
            )}
          </Card>
        ))}
      </div>

      {hasNextPage && (
        <Button variant="secondary" onClick={() => fetchNextPage()} disabled={isFetchingNextPage} className="w-full">
          {isFetchingNextPage ? "加载中…" : "加载更多"}
        </Button>
      )}
    </div>
  );
}
