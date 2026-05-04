import Link from "next/link";

const PILLARS = [
  {
    title: "10 sources, one feed",
    body: "Ticketmaster + Eventbrite + Meetup + 7 scraped local calendars (FuncheapSF, 19hz, DoTheBay, SF Station, Minnesota Street, Reddit, newsletter parsing). Deduped on the way in.",
  },
  {
    title: "Recommendations that learn",
    body: "Weighted vibe match, popularity, freshness, and diversity scoring. 30-day half-life decay on user signals — the more you save, the better it gets.",
  },
  {
    title: "Plain-English planner",
    body: "Tell the concierge what you want (\"date night in the Mission Saturday\") and get a sequenced itinerary with travel buffers between stops.",
  },
  {
    title: "Built for sharing",
    body: "Shortlist folders with soft-RSVP votes and public share links. Plan a night out together without leaving the app.",
  },
];

export default function HomePage() {
  return (
    <div className="space-y-12 pb-12">
      <section className="space-y-6 pt-4">
        <div className="space-y-3">
          <p className="inline-block rounded-full border border-brand-400/40 bg-brand-500/10 px-3 py-1 text-xs font-medium uppercase tracking-wider text-brand-200">
            Reference deployment · SF Bay Area
          </p>
          <h2 className="text-4xl font-semibold leading-tight sm:text-5xl">
            The fragmented event landscape, defragmented.
          </h2>
          <p className="max-w-2xl text-lg text-slate-300">
            Truth of Fun pulls events from ticketing APIs, public calendars, and community sources into one
            deduplicated feed — and ranks them with a recommender that learns from what you actually do.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          <Link
            href="/explore"
            className="rounded-ui bg-brand-500 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-brand-400"
          >
            Explore events
          </Link>
          <Link
            href="/planner"
            className="rounded-ui border border-slate-700 bg-slate-900 px-5 py-2.5 text-sm font-medium text-slate-100 transition hover:border-slate-600 hover:bg-slate-800"
          >
            Plan something
          </Link>
          <Link
            href="/login"
            className="rounded-ui px-5 py-2.5 text-sm font-medium text-slate-300 transition hover:text-slate-100"
          >
            Sign in →
          </Link>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {PILLARS.map((pillar) => (
          <div
            key={pillar.title}
            className="rounded-ui border border-slate-800 bg-slate-900/60 p-5"
          >
            <h3 className="text-base font-semibold text-slate-100">{pillar.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-300">{pillar.body}</p>
          </div>
        ))}
      </section>

      <section className="rounded-ui border border-slate-800 bg-slate-900/60 p-6">
        <h3 className="text-base font-semibold text-slate-100">How it works</h3>
        <ol className="mt-4 grid gap-4 text-sm text-slate-300 sm:grid-cols-3">
          <li className="space-y-1">
            <span className="block text-xs font-mono text-brand-200">01 · ingest</span>
            <p>10 source connectors run on a 6-hour cycle with canary alerting on zero-result anomalies.</p>
          </li>
          <li className="space-y-1">
            <span className="block text-xs font-mono text-brand-200">02 · dedupe</span>
            <p>Fuzzy title match (Levenshtein ≥ 85%) inside a 2-hour window. Tier-1 sources win on conflict.</p>
          </li>
          <li className="space-y-1">
            <span className="block text-xs font-mono text-brand-200">03 · rank</span>
            <p>Vibe (50%) + popularity (25%) + freshness (15%) + diversity (10%), with category-spread penalty.</p>
          </li>
        </ol>
      </section>
    </div>
  );
}
