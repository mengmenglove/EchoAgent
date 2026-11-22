// 服务端组件：只负责从 URL 读出 id，交给客户端组件渲染。
// Next.js 16 里 params 是 Promise；开启 cacheComponents 后，读取它（运行时数据）的地方
// 必须包在 <Suspense> 里，这样页面外壳能先静态渲染、立即返回，动态部分随后流式补上。
import { Suspense } from "react";
import { Spinner } from "@/components/ui";
import { JobDetail } from "./JobDetail";

async function JobById({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobDetail id={id} />;
}

export default function JobPage({ params }: PageProps<"/jobs/[id]">) {
  return (
    <Suspense fallback={<Spinner />}>
      <JobById params={params} />
    </Suspense>
  );
}
