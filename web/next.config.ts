import type { NextConfig } from "next";

// FastAPI 的地址。浏览器只访问 Next.js（同源），/api/* 由 Next.js 转发过去，
// 这样 Cookie、CORS 都不用额外配置。
const API_ORIGIN = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // SSE 是流式响应，压缩会让中间层攒满缓冲区才往下发，进度条就会"一下子全到"
  compress: false,
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
