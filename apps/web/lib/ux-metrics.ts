const KEY = "baeUxMetricsV1";

type Metrics = {
  firstVisitAt?: number;
  firstResultsAt?: number;
  firstSaveAt?: number;
  welcomeChoice?: "browse" | "personalize";
};

function readMetrics(): Metrics {
  if (typeof window === "undefined") {
    return {};
  }
  const raw = localStorage.getItem(KEY);
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw) as Metrics;
  } catch {
    return {};
  }
}

function writeMetrics(next: Metrics) {
  if (typeof window === "undefined") {
    return;
  }
  localStorage.setItem(KEY, JSON.stringify(next));
}

export function markFirstVisit() {
  const metrics = readMetrics();
  if (!metrics.firstVisitAt) {
    writeMetrics({ ...metrics, firstVisitAt: Date.now() });
  }
}

export function markWelcomeChoice(choice: "browse" | "personalize") {
  const metrics = readMetrics();
  writeMetrics({ ...metrics, welcomeChoice: choice });
}

export function markFirstResults() {
  const metrics = readMetrics();
  if (!metrics.firstResultsAt) {
    writeMetrics({ ...metrics, firstResultsAt: Date.now() });
  }
}

export function markFirstSave() {
  const metrics = readMetrics();
  if (!metrics.firstSaveAt) {
    writeMetrics({ ...metrics, firstSaveAt: Date.now() });
  }
}

export function readTimeToValueSeconds() {
  const metrics = readMetrics();
  if (!metrics.firstVisitAt) {
    return null;
  }
  return {
    toResults:
      metrics.firstResultsAt && metrics.firstResultsAt > metrics.firstVisitAt
        ? Math.round((metrics.firstResultsAt - metrics.firstVisitAt) / 1000)
        : null,
    toFirstSave:
      metrics.firstSaveAt && metrics.firstSaveAt > metrics.firstVisitAt
        ? Math.round((metrics.firstSaveAt - metrics.firstVisitAt) / 1000)
        : null,
  };
}
