"use client";

import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  hint?: string;
};

export function Select({ className, label, hint, id, children, ...props }: Props) {
  const selectId = id || props.name;
  return (
    <label className="block space-y-1.5">
      {label ? <span className="text-sm text-slate-200">{label}</span> : null}
      <select
        id={selectId}
        className={cn(
          "w-full rounded-ui border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300",
          className
        )}
        {...props}
      >
        {children}
      </select>
      {hint ? <span className="text-xs text-slate-400">{hint}</span> : null}
    </label>
  );
}
