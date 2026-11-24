import type { NextConfig } from "next";

// FastAPI 的地址。浏览器只访问 Next.js（同源），/api/* 由 Next.js 转发过去，
// 这样 Cookie、CORS 都不用额外配置。
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // SSE 是流式响应，压缩会让中间层攒满缓冲区才往下发，进度条就会"一下子全到"
  compress: false,
  experimental: {
    // rewrites 转发给 FastAPI 的代理默认 30 秒超时。聊天的语音合成、长任务的 SSE 都可能更久，
    // 调到 5 分钟（后端也会每 10 秒发一次心跳）
    proxyTimeout: 5 * 60_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
