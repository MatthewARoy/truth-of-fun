"use client";

import { useId, type SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  hint?: string;
};

export function Select({ className, label, hint, id, children, ...props }: Props) {
  const generatedId = useId();
  const selectId = id || generatedId;
  const hintId = hint ? `${selectId}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      {label ? <label htmlFor={selectId} className="block text-sm text-slate-200">{label}</label> : null}
      <select
        id={selectId}
        aria-describedby={hintId}
        className={cn(
          "block w-full rounded-ui border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300",
          className
        )}
        {...props}
      >
        {children}
      </select>
      {hint ? <p id={hintId} className="text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}
