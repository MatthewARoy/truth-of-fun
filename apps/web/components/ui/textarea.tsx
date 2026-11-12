"use client";

import { useId, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: string;
  hint?: string;
};

export function Textarea({ className, label, hint, id, ...props }: Props) {
  const generatedId = useId();
  const textareaId = id || generatedId;
  const hintId = hint ? `${textareaId}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      {label ? <label htmlFor={textareaId} className="block text-sm text-slate-200">{label}</label> : null}
      <textarea
        id={textareaId}
        aria-describedby={hintId}
        className={cn(
          "block w-full rounded-ui border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100",
          "placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300",
          className
        )}
        {...props}
      />
      {hint ? <p id={hintId} className="text-xs text-slate-400">{hint}</p> : null}
    </div>
  );
}
