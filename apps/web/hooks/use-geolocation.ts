"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type GeolocationState =
  | { status: "idle" }
  | { status: "locating" }
  | { status: "active"; lat: number; lng: number }
  | { status: "denied" }
  | { status: "unavailable" }
  | { status: "unsupported" };

/**
 * One-shot browser location for "Near me". The position stays in memory only:
 * it is not stored, and it is never written to the URL.
 */
export function useGeolocation() {
  const [state, setState] = useState<GeolocationState>({ status: "idle" });
  // Ignore an answer that arrives after the user turned "Near me" back off.
  const requestId = useRef(0);

  useEffect(() => () => { requestId.current += 1; }, []);

  const locate = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setState({ status: "unsupported" });
      return;
    }
    const id = ++requestId.current;
    setState({ status: "locating" });
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (requestId.current !== id) return;
        // ~100 m precision is plenty for a radius measured in miles.
        setState({
          status: "active",
          lat: Number(position.coords.latitude.toFixed(3)),
          lng: Number(position.coords.longitude.toFixed(3)),
        });
      },
      (error) => {
        if (requestId.current !== id) return;
        setState({ status: error.code === error.PERMISSION_DENIED ? "denied" : "unavailable" });
      },
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 5 * 60_000 }
    );
  }, []);

  const clear = useCallback(() => {
    requestId.current += 1;
    setState({ status: "idle" });
  }, []);

  return { state, locate, clear };
}
