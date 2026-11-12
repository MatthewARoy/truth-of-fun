import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ExploreClient } from "./explore-client";

// Explore keeps its filters in the query string, and reading the query string
// in a prerendered page has to happen below a Suspense boundary.
export default function ExplorePage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold">Explore Bay Area events</h1>
        <p className="text-sm text-slate-400">
          Search by keyword, or narrow by date, region, category and price. Every search has its own
          link you can bookmark or share.
        </p>
      </div>
      <Suspense fallback={<ExploreFallback />}>
        <ExploreClient />
      </Suspense>
    </div>
  );
}

function ExploreFallback() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading events">
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-8 w-2/3" />
      <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="space-y-3">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-full" />
          </Card>
        ))}
      </div>
    </div>
  );
}
