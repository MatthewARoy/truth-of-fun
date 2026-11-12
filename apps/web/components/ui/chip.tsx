"use client";

import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-pressed"> & {
  /** Whether this filter is currently applied; exposed as aria-pressed. */
  pressed: boolean;
  size?: "sm" | "md";
};

/** A toggle button for filters and multi-select options. */
export function Chip({ pressed, size = "sm", className, type = "button", ...props }: Props) {
  return (
    <button
      type={type}
      aria-pressed={pressed}
      className={cn(
        "rounded-full border transition disabled:cursor-not-allowed disabled:opacity-60",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950",
        size === "sm" ? "px-3 py-1.5 text-xs" : "px-4 py-2 text-sm",
        pressed
          ? "border-brand-400 bg-brand-500/20 text-brand-100"
          : "border-slate-700 bg-slate-800/50 text-slate-300 hover:border-slate-600 hover:bg-slate-800",
        className
      )}
      {...props}
    />
  );
}
