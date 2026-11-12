"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";

// Replaces the root layout when the layout itself fails, so it must render its
// own <html> and <body> and cannot rely on globals.css, the nav, or the auth
// provider. Styles are inline for that reason. Plain <a>/<button>: the router
// may be the thing that broke.
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  const button = {
    borderRadius: "0.75rem",
    padding: "0.5rem 1rem",
    fontSize: "0.875rem",
    fontWeight: 500,
    cursor: "pointer",
    textDecoration: "none",
  } as const;

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#020617",
          color: "#f1f5f9",
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
        }}
      >
        <title>Something went wrong | Truth of Fun</title>
        <main role="alert" style={{ maxWidth: "32rem", padding: "1.5rem", textAlign: "center" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600, margin: "0 0 0.75rem" }}>Something went wrong</h1>
          <p style={{ fontSize: "0.875rem", color: "#cbd5e1", margin: "0 0 1.25rem", lineHeight: 1.6 }}>
            Truth of Fun hit an unexpected problem and could not show this page. Try again, or go back
            to the home page.
          </p>
          {error.digest ? (
            <p style={{ fontSize: "0.75rem", color: "#64748b", margin: "0 0 1.25rem" }}>
              Reference: <span style={{ fontFamily: "ui-monospace, monospace" }}>{error.digest}</span>
            </p>
          ) : null}
          <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => retry()}
              style={{ ...button, border: "none", background: "#139ec9", color: "#ffffff" }}
            >
              Try again
            </button>
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/" style={{ ...button, border: "1px solid #334155", background: "#0f172a", color: "#f1f5f9" }}>
              Go to the home page
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
