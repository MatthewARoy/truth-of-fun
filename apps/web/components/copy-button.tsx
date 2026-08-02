"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Props = {
  value: string;
  label?: string;
  copiedLabel?: string;
  variant?: "primary" | "secondary" | "ghost";
  fullWidth?: boolean;
};

/** Copies `value` to the clipboard and confirms it for a couple of seconds. */
export function CopyButton({
  value,
  label = "Copy",
  copiedLabel = "Copied",
  variant = "secondary",
  fullWidth = false,
}: Props) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimer.current) clearTimeout(resetTimer.current);
    };
  }, []);

  async function handleCopy() {
    try {
      // Absent over plain HTTP, which is how this gets opened on a phone on a
      // LAN address during development.
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (resetTimer.current) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => setState("idle"), 2000);
  }

  return (
    <Button
      type="button"
      variant={variant}
      fullWidth={fullWidth}
      onClick={handleCopy}
      aria-live="polite"
    >
      {state === "copied" ? copiedLabel : state === "failed" ? "Press ⌘C to copy" : label}
    </Button>
  );
}
