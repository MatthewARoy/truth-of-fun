import Link from "next/link";

type Props = {
  title?: string;
  message?: string;
};

/** Shared 404 body: the root not-found page and pages that discover a missing record client-side. */
export function NotFoundContent({
  title = "We couldn't find that page",
  message = "The link may be out of date, or the page may have moved. Events come and go, so an old event link can stop working once the event is over.",
}: Props) {
  return (
    <section className="mx-auto max-w-xl space-y-4 py-12 text-center">
      <p className="text-sm font-medium uppercase tracking-wider text-brand-200">404</p>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-sm text-slate-300">{message}</p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link
          href="/explore"
          className="rounded-ui bg-brand-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-400 hover:text-white"
        >
          Explore events
        </Link>
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
