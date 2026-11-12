import type { ReactNode } from "react";

/**
 * Shared frame for /privacy and /terms. Both documents are scaffolds written
 * from what the code does; the notice at the top must stay until counsel has
 * reviewed and replaced the text.
 */
export function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl space-y-6">
      <div
        role="note"
        aria-label="Draft notice"
        className="rounded-ui border-2 border-amber-500 bg-amber-900/40 px-4 py-3 text-sm text-amber-50"
      >
        <p className="text-base font-semibold uppercase tracking-wide">Draft: pending legal review</p>
        <p className="mt-1">
          This text is a working draft that describes how the product currently behaves. It has not
          been reviewed by a lawyer, is not final, and must not be relied on as the binding version.
          Text in [square brackets] is a placeholder that still has to be filled in.
        </p>
      </div>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <div className="space-y-6 text-sm leading-relaxed text-slate-300">{children}</div>
    </article>
  );
}

export function LegalSection({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold text-slate-100">{heading}</h2>
      {children}
    </section>
  );
}
