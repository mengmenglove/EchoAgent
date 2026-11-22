// 极简的基础组件。项目长大后可以换成 shadcn/ui。
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { STATUS_COLOR, STATUS_LABEL } from "@/lib/format";
import type { JobStatus } from "@/lib/schemas";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const styles = {
    primary: "bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-300",
    secondary: "border border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-50 disabled:text-zinc-400",
    danger: "border border-red-200 bg-white text-red-600 hover:bg-red-50",
    ghost: "text-zinc-600 hover:bg-zinc-100",
  }[variant];
  return (
    <button
      className={`inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${styles} ${className}`}
      {...props}
    />
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-zinc-200 bg-white p-5 shadow-sm ${className}`}>{children}</div>;
}

export function StatusBadge({ status }: { status: JobStatus }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLOR[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function ErrorText({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return <p className="mt-1 text-sm text-red-600">{children}</p>;
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}
