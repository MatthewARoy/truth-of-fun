import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Props = {
  children: ReactNode;
  active?: boolean;
  className?: string;
};

export function Badge({ children, active = false, className }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs",
        active ? "border-brand-500 bg-brand-500/20 text-brand-100" : "border-slate-700 bg-slate-800 text-slate-300",
        className
      )}
    >
      {children}
    </span>
  );
}
