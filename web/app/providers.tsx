"use client";

// QueryClientProvider 依赖 React Context，只能在客户端组件里用，所以单独拆出这个文件，
// 根布局（服务端组件）引入它即可。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  // 用 useState 保证每个浏览器会话只创建一个 QueryClient（不会每次渲染都新建）
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            // 401/403/404 重试也没用，直接失败
            retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
