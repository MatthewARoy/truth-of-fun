import Link from "next/link";
import { SITE_NAME } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="border-t border-slate-800 pt-4 text-xs text-slate-400">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p>
          {SITE_NAME} lists events gathered from third-party sources. Always confirm details with the
          organizer before you go.
        </p>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-4 gap-y-1">
          <Link href="/explore">Explore</Link>
          <Link href="/planner">Plan something</Link>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
        </nav>
      </div>
    </footer>
  );
}
