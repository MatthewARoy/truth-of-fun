import type { Metadata } from "next";
import Link from "next/link";
import { FALLBACK_REGIONS } from "@/lib/explore-params";
import { SITE_DESCRIPTION, SITE_NAME, SITE_TAGLINE } from "@/lib/site";

const TITLE = `${SITE_NAME} — ${SITE_TAGLINE}`;

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: SITE_DESCRIPTION,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website", siteName: SITE_NAME, locale: "en_US", url: "/", title: TITLE, description: SITE_DESCRIPTION,
  },
  twitter: { card: "summary", title: TITLE, description: SITE_DESCRIPTION },
};

const REGION_BLURBS: Record<string, string> = {
  sf: "The city, from the Mission to the Richmond.",
  east_bay: "Oakland, Berkeley and the cities east of the bay.",
  peninsula: "Daly City down through San Mateo and Palo Alto.",
  south_bay: "San Jose and Silicon Valley.",
  north_bay: "Marin, Sonoma and Napa.",
};

const FEATURES = [
  {
    title: "One place to look",
    body: "Concerts, comedy, food, outdoor meetups, talks and community events, gathered from ticketing sites, public calendars and local listings so you don't have to check each one.",
  },
  {
    title: "Filter it your way",
    body: "Narrow by region or city, by date, by category, or to free events only. Switch to the map, or see what's happening near you.",
  },
  {
    title: "Plan a day or night out",
    body: "Describe what you're in the mood for in plain English and get a sequence of stops with time to get from one to the next.",
  },
  {
    title: "Decide together",
    body: "Send a plan as a link, or collect ideas in a shared folder and let friends vote on them.",
  },
];

const PRIMARY_CTA =
  "rounded-ui bg-brand-500 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-brand-400 hover:text-white";
const SECONDARY_CTA =
  "rounded-ui border border-slate-700 bg-slate-900 px-5 py-2.5 text-sm font-medium text-slate-100 transition hover:border-slate-600 hover:bg-slate-800 hover:text-slate-100";

export default function HomePage() {
  return (
    <div className="space-y-12 pb-12">
      <section className="space-y-6 pt-4">
        <div className="space-y-3">
          <p className="inline-block rounded-full border border-brand-400/40 bg-brand-500/10 px-3 py-1 text-xs font-medium uppercase tracking-wider text-brand-200">
            San Francisco Bay Area
          </p>
          <h1 className="text-4xl font-semibold leading-tight sm:text-5xl">
            Find something fun to do around the Bay.
          </h1>
          <p className="max-w-2xl text-lg text-slate-300">
            {SITE_NAME} brings events from across the Bay Area into one searchable list. See
            what&apos;s on tonight or this weekend, near you or across the bridge, then turn it into a
            plan.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          <Link href="/explore" className={PRIMARY_CTA}>Explore events</Link>
          <Link href="/planner" className={SECONDARY_CTA}>Plan something</Link>
          <Link
            href="/login"
            className="rounded-ui px-5 py-2.5 text-sm font-medium text-slate-300 transition hover:text-slate-100"
          >
            Sign in <span aria-hidden="true">&rarr;</span>
          </Link>
        </div>

        <div className="flex flex-wrap gap-2 text-sm">
          <Link href="/explore?when=tonight" className="rounded-full border border-slate-700 px-3 py-1.5 text-slate-200 hover:border-slate-500">
            Tonight
          </Link>
          <Link href="/explore?when=this_weekend" className="rounded-full border border-slate-700 px-3 py-1.5 text-slate-200 hover:border-slate-500">
            This weekend
          </Link>
          <Link href="/explore?free=1" className="rounded-full border border-slate-700 px-3 py-1.5 text-slate-200 hover:border-slate-500">
            Free events
          </Link>
        </div>
      </section>

      <section className="space-y-4" aria-labelledby="home-regions">
        <h2 id="home-regions" className="text-xl font-semibold">Browse by region</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {FALLBACK_REGIONS.map((region) => (
            <li key={region.id}>
              <Link
                href={`/explore?region=${region.id}`}
                className="block h-full rounded-ui border border-slate-800 bg-slate-900/60 p-4 transition hover:border-brand-400/60"
              >
                <span className="block text-base font-semibold text-slate-100">{region.label}</span>
                <span className="mt-1 block text-sm text-slate-400">{REGION_BLURBS[region.id]}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-4" aria-labelledby="home-features">
        <h2 id="home-features" className="text-xl font-semibold">What you can do here</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {FEATURES.map((feature) => (
            <div key={feature.title} className="rounded-ui border border-slate-800 bg-slate-900/60 p-5">
              <h3 className="text-base font-semibold text-slate-100">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">{feature.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-ui border border-slate-800 bg-slate-900/60 p-6" aria-labelledby="home-know">
        <h2 id="home-know" className="text-base font-semibold text-slate-100">Good to know</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-slate-300">
          <li>
            Browsing is open to everyone. An account lets you save events, get recommendations and
            share plans.
          </li>
          <li>
            Listings come from other sites and link back to them. Details can change, so check the
            event&apos;s own page before you head out.
          </li>
          <li>
            When a source doesn&apos;t publish a start time or a price, we say so instead of guessing.
          </li>
        </ul>
      </section>
    </div>
  );
}
