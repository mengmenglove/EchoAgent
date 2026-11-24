// Next.js 16 的 Proxy（原来叫 Middleware）：请求到达页面之前运行。
// 这里只做"乐观检查"——有没有登录 Cookie，没有就跳登录页，体验更顺。
// 真正的鉴权在 FastAPI（校验 JWT 签名和过期时间），官方文档也明确说 Proxy 不该做完整的会话校验。
import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  if (!request.cookies.has("echo_session")) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
}

export const config = {
  matcher: ["/studio/:path*", "/chat/:path*", "/jobs/:path*", "/history/:path*", "/account/:path*"],
};
