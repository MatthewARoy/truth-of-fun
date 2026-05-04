"use client";

import type { TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: string;
  hint?: string;
};

export function Textarea({ className, label, hint, id, ...props }: Props) {
  const textareaId = id || props.name;
  return (
    <label className="block space-y-1.5">
      {label ? <span className="text-sm text-slate-200">{label}</span> : null}
      <textarea
        id={textareaId}
        className={cn(
          "w-full rounded-ui border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100",
          "placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300",
          className
        )}
        {...props}
      />
      {hint ? <span className="text-xs text-slate-400">{hint}</span> : null}
    </label>
  );
}
