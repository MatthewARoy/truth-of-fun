import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Props = {
  children: ReactNode;
  className?: string;
  padding?: "default" | "none";
};

export function Card({ children, className, padding = "default" }: Props) {
  return (
    <div
      className={cn(
        "rounded-ui border border-slate-800 bg-slate-900 overflow-hidden",
        padding === "default" && "p-4",
        className
      )}
    >
      {children}
    </div>
  );
}
