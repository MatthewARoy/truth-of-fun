import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Props = {
  children: ReactNode;
  className?: string;
};

export function Card({ children, className }: Props) {
  return <div className={cn("rounded-ui border border-slate-800 bg-slate-900 p-4", className)}>{children}</div>;
}
