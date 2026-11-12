"use client";

import { useId, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
};

// The label names the field and the hint describes it (aria-describedby), so
// assistive technology announces "New password" rather than the label and the
// hint run together. Without a visible label, pass aria-label.
export function Input({ className, label, hint, id, ...props }: Props) {
  const generatedId = useId();
  const inputId = id || generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      {label ? <label htmlFor={inputId} className="block text-sm text-slate-200">{label}</label> : null}
      <input
        id={inputId}
        aria-describedby={hintId}
        className={cn(
          "block w-full rounded-ui border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100",
          "placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300",
          "disabled:cursor-not-allowed disabled:opacity-60",
          className
        )}
        {...props}
      />
      {hint ? <p id={hintId} className="text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}
