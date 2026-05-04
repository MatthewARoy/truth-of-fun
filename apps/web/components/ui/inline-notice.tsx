import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "info" | "success" | "error";

type Props = {
  children: ReactNode;
  tone?: Tone;
  className?: string;
};

const toneStyles: Record<Tone, string> = {
  info: "border-slate-700 bg-slate-900 text-slate-200",
  success: "border-emerald-700 bg-emerald-900/40 text-emerald-100",
  error: "border-rose-700 bg-rose-900/40 text-rose-100",
};

export function InlineNotice({ children, tone = "info", className }: Props) {
  return (
    <p className={cn("rounded-ui border px-3 py-2 text-sm", toneStyles[tone], className)}>
      {children}
    </p>
  );
}
