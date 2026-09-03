"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const REFRESH_INTERVAL_MS = 30_000;

// Live feel without a socket: the server components re-render with fresh
// durable state on every refresh; this client shell only schedules them.
export function AutoRefresh({
  generatedAt,
  intervalMs = REFRESH_INTERVAL_MS,
}: {
  generatedAt: string;
  intervalMs?: number;
}) {
  const router = useRouter();
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    const timer = setInterval(() => {
      if (!pausedRef.current) {
        router.refresh();
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }, [router, intervalMs]);

  const stamp = new Date(generatedAt);
  const label = Number.isNaN(stamp.getTime())
    ? generatedAt
    : `${stamp.toISOString().slice(11, 19)} UTC`;

  return (
    <div className="kontrol-refresh">
      <span className="muted">Son yenileme: {label}</span>
      <button type="button" onClick={() => router.refresh()}>
        Yenile
      </button>
      <button type="button" onClick={() => setPaused((value) => !value)}>
        {paused ? "Otomatik yenilemeyi aç" : "Otomatik yenilemeyi durdur"}
      </button>
      <span className="muted">
        {paused
          ? "otomatik yenileme kapalı"
          : `${Math.round(intervalMs / 1000)} sn'de bir yenilenir`}
      </span>
    </div>
  );
}
