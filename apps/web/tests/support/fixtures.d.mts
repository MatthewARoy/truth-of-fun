import type {
  EventDetailResponse, FolderDetailResponse, PortableItineraryResponse,
} from "@truth-of-fun/api-client";

export const SSR_EVENT: EventDetailResponse;
export const SSR_ESTIMATED_EVENT: EventDetailResponse;
export const SSR_CANCELLED_EVENT: EventDetailResponse;
export const SSR_EVENTS: EventDetailResponse[];
export const MISSING_EVENT_ID: number;
export const UNREACHABLE_EVENT_ID_FROM: number;
export const SSR_PLAN_TOKEN: string;
export const SSR_PLAN: PortableItineraryResponse;
export const SSR_FOLDER_TOKEN: string;
export const SSR_FOLDER: FolderDetailResponse;
