// (app) 是路由组：括号里的名字不会出现在 URL 里，只用来给这几个页面共用一个带导航栏的布局。
import { Suspense } from "react";
import { NavBar } from "@/components/NavBar";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      {/* NavBar 用了 usePathname()：在动态路由（/jobs/[id]）下它是运行时数据，
          cacheComponents 要求包在 Suspense 里，先渲染一个等高的占位，避免页面跳动 */}
      <Suspense fallback={<div className="h-14 border-b border-zinc-200 bg-white" />}>
        <NavBar />
      </Suspense>
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </>
  );
}
