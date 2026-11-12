"use client"; // Error boundaries must be Client Components

import Link from "next/link";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function RouteError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    // For whoever is debugging; the page itself never shows the message or stack.
    console.error(error);
  }, [error]);

  return (
    <section className="mx-auto max-w-xl space-y-4 py-12 text-center" role="alert">
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="text-sm text-slate-300">
        This page hit an unexpected problem. It is not something you did. Try again, and if it keeps
        happening, head back to the home page.
      </p>
      {error.digest ? (
        <p className="text-xs text-slate-500">
          Reference: <span className="font-mono">{error.digest}</span>
        </p>
      ) : null}
      <div className="flex flex-wrap justify-center gap-3">
        <Button type="button" onClick={() => retry()}>Try again</Button>
        <Link
          href="/"
          className="rounded-ui border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-slate-600 hover:bg-slate-800"
        >
          Go to the home page
        </Link>
      </div>
    </section>
  );
}
