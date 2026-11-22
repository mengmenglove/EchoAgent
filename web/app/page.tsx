import { redirect } from "next/navigation";

export default function Home() {
  redirect("/studio"); // 没登录的话 proxy.ts 会再跳到 /login
}
