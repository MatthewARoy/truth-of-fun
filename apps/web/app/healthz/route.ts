// Liveness probe for the container healthcheck: answers as long as the Next.js
// server is accepting requests. It deliberately checks nothing else (the API
// has its own health endpoints), so an API outage does not restart the web tier.
export const dynamic = "force-dynamic";

export function GET() {
  return new Response("ok", {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
