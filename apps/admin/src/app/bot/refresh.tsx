"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export function BotRefresh() {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden && !document.activeElement?.closest("form"))
        router.refresh();
    }, 30_000);
    return () => clearInterval(timer);
  }, [router]);
  return (
    <button type="button" onClick={() => router.refresh()}>
      İlerlemeyi yenile ↻
    </button>
  );
}
