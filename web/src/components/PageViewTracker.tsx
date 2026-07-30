import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";

const reportedEvents = new Map<string, string>();

function eventIdFor(key: string) {
  const existing = reportedEvents.get(key);
  if (existing) return existing;
  const value =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
          const random = Math.floor(Math.random() * 16);
          const value = character === "x" ? random : (random & 0x3) | 0x8;
          return value.toString(16);
        });
  reportedEvents.set(key, value);
  return value;
}

export function PageViewTracker() {
  const location = useLocation();

  useEffect(() => {
    const runtimeKey = `${performance.timeOrigin}:${location.key}:${location.pathname}`;
    if (reportedEvents.has(runtimeKey)) return;
    void api
      .recordPageView(eventIdFor(runtimeKey), location.pathname)
      .catch(() => undefined);
  }, [location.key, location.pathname]);

  return null;
}
