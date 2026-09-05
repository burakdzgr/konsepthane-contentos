"use client";

import { useEffect, useState } from "react";

// The gateway's live ChatGPT session inside the operations grid: one JPEG
// frame every few seconds through the authenticated proxy. View only —
// the Nstbrowser window on the host keeps running; it just no longer has
// to be in front of the operator.

const FRAME_INTERVAL_MS = 3000;

export function BrowserView({ available }: { available: boolean }) {
  const [stamp, setStamp] = useState<number>(() => Date.now());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!available) {
      return undefined;
    }
    const timer = setInterval(() => setStamp(Date.now()), FRAME_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [available]);

  if (!available) {
    return (
      <div className="ops-browser" role="img" aria-label="Tarayıcı görüntüsü">
        Bağlı bir tarayıcı oturumu yok. Gateway ayakta ve ChatGPT hesabı hazır
        olduğunda canlı görüntü burada belirir.
      </div>
    );
  }
  return (
    <div className="ops-browser" role="img" aria-label="Tarayıcı görüntüsü">
      {failed ? (
        <span>Kare alınamadı; oturum meşgul ya da kapalı olabilir.</span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- live frames, no optimisation
        <img
          src={`/operasyon/screenshot?ts=${stamp}`}
          alt="Gateway tarayıcı oturumunun canlı görüntüsü"
          onError={() => setFailed(true)}
          onLoad={() => setFailed(false)}
        />
      )}
    </div>
  );
}
