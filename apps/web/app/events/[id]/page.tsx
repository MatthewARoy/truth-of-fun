import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { ApiClientError, type EventDetailResponse } from "@truth-of-fun/api-client";
import { EventDetail } from "@/components/event-detail";
import { EventDetailLoader } from "@/components/event-detail-loader";
import { SERVER_REQUEST, serverApiClient } from "@/lib/api/server";
import { eventLongStartLabel, placeLabel, safeImageUrl, statusNotice } from "@/lib/event-format";
import { eventJsonLd, serializeJsonLd } from "@/lib/event-jsonld";
import { NO_INDEX, pageMetadata, summarize } from "@/lib/metadata";

type Props = { params: Promise<{ id: string }> };

type Loaded =
  | { state: "ok"; event: EventDetailResponse }
  | { state: "missing" }
  /** The API could not be reached from the server; the browser will try itself. */
  | { state: "unavailable" };

// Event ids are positive integers; anything else can never be an event.
function parseEventId(raw: string): number | null {
  return /^[1-9]\d{0,14}$/.test(raw) ? Number(raw) : null;
}

// cache(): generateMetadata and the page share one API call per request.
const loadEvent = cache(async (id: number): Promise<Loaded> => {
  try {
    return { state: "ok", event: await serverApiClient().getEvent(id, SERVER_REQUEST) };
  } catch (error) {
    if (error instanceof ApiClientError && (error.status === 404 || error.status === 422)) {
      return { state: "missing" };
    }
    return { state: "unavailable" };
  }
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = parseEventId((await params).id);
  if (id === null) return { title: "Event not found", robots: NO_INDEX };
  const loaded = await loadEvent(id);
  if (loaded.state === "missing") return { title: "Event not found", robots: NO_INDEX };
  const path = `/events/${id}`;
  if (loaded.state === "unavailable") {
    return pageMetadata({ title: "Event", description: "Event details on Truth of Fun.", path });
  }
  const { event } = loaded;
  const notice = statusNotice(event.status);
  const facts = `${notice ? `${notice.label}. Originally ` : ""}${eventLongStartLabel(event)} · ${placeLabel(event)}`;
  const blurb = summarize(event.description, 160);
  return pageMetadata({
    title: event.title,
    description: blurb ? `${facts}. ${blurb}` : `${facts}.`,
    path,
    image: safeImageUrl(event.image_url),
  });
}

export default async function EventPage({ params }: Props) {
  const id = parseEventId((await params).id);
  if (id === null) notFound();
  const loaded = await loadEvent(id);
  if (loaded.state === "missing") notFound();
  if (loaded.state === "unavailable") return <EventDetailLoader eventId={id} />;
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(eventJsonLd(loaded.event)) }}
      />
      <EventDetail event={loaded.event} />
    </>
  );
}
