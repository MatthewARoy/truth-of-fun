"use client";

import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  fullWidth?: boolean;
};

const variantStyles: Record<Variant, string> = {
  primary: "bg-brand-500 text-white hover:bg-brand-400",
  secondary: "bg-slate-800 text-slate-100 hover:bg-slate-700",
  ghost: "bg-transparent text-slate-200 hover:bg-slate-800",
  danger: "bg-rose-800 text-rose-100 hover:bg-rose-700",
};

const sizeStyles: Record<Size, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  fullWidth = false,
  disabled,
  ...props
}: Props) {
  return (
    <button
      className={cn(
        "rounded-ui font-medium transition disabled:cursor-not-allowed disabled:opacity-60",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950",
        variantStyles[variant],
        sizeStyles[size],
        fullWidth && "w-full",
        className
      )}
      disabled={disabled}
      {...props}
    />
  );
}
