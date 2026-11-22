"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { Button, Card, ErrorText } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { AuthSchema, type AuthInput } from "@/lib/schemas";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [serverError, setServerError] = useState<string>();
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AuthInput>({ resolver: zodResolver(AuthSchema) });

  async function onSubmit(values: AuthInput) {
    setServerError(undefined);
    try {
      await api.post(`/api/auth/${mode}`, values);
      qc.clear(); // 换了账号，清掉上一个账号的缓存数据
      const next = params.get("next");
      router.replace(next?.startsWith("/") ? next : "/studio"); // 只允许站内跳转，防开放重定向
    } catch (e) {
      setServerError(e instanceof ApiError ? e.message : "网络错误");
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <h1 className="text-xl font-semibold">{mode === "login" ? "登录回音" : "注册回音"}</h1>
      <p className="mt-1 text-sm text-zinc-500">一句话需求，自动写稿、配音、出字幕</p>
      <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4">
        <div>
          <label className="text-sm font-medium">邮箱</label>
          <input
            {...register("email")}
            type="email"
            autoComplete="email"
            className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2"
          />
          <ErrorText>{errors.email?.message}</ErrorText>
        </div>
        <div>
          <label className="text-sm font-medium">密码</label>
          <input
            {...register("password")}
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2"
          />
          <ErrorText>{errors.password?.message}</ErrorText>
        </div>
        <ErrorText>{serverError}</ErrorText>
        <Button type="submit" disabled={isSubmitting} className="w-full">
          {isSubmitting ? "请稍候…" : mode === "login" ? "登录" : "注册并领取体验额度"}
        </Button>
      </form>
      <button
        type="button"
        onClick={() => setMode(mode === "login" ? "register" : "login")}
        className="mt-4 w-full text-center text-sm text-blue-600"
      >
        {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
      </button>
    </Card>
  );
}

export default function LoginPage() {
  // useSearchParams 需要包在 Suspense 里，否则整页都无法预渲染
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
