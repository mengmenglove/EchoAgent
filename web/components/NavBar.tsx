"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useMe } from "@/lib/hooks";

const LINKS = [
  { href: "/studio", label: "创作" },
  { href: "/chat", label: "聊天" },
  { href: "/history", label: "历史" },
  { href: "/account", label: "账户" },
];

export function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: me } = useMe();

  async function logout() {
    await api.post("/api/auth/logout");
    qc.clear();
    router.replace("/login");
  }

  return (
    <header className="border-b border-zinc-200 bg-white">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-6 px-4">
        <Link href="/studio" className="font-semibold">
          回音 <span className="text-zinc-400">EchoAgent</span>
        </Link>
        <nav className="flex gap-1">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`rounded-md px-3 py-1.5 text-sm ${
                pathname.startsWith(l.href) ? "bg-zinc-100 font-medium" : "text-zinc-600 hover:bg-zinc-50"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4 text-sm">
          {me && (
            <>
              <span className="text-zinc-500">{me.email}</span>
              <span className="rounded-md bg-blue-50 px-2 py-1 text-blue-700">额度 {me.credits_balance}</span>
            </>
          )}
          <button onClick={logout} className="text-zinc-500 hover:text-zinc-800">
            退出
          </button>
        </div>
      </div>
    </header>
  );
}
