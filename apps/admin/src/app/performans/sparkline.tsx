// Minimal inline SVG sparkline drawn from REAL snapshot values; no chart
// library. Fewer than two finite points is rendered as an honest
// "Yetersiz veri" instead of an empty or flat line.

export function Sparkline({
  values,
  label,
  width = 180,
  height = 40,
  lowerIsBetter = false,
}: {
  values: ReadonlyArray<number | null | undefined>;
  label: string;
  width?: number;
  height?: number;
  // Position: a LOWER number is better, so the line is flipped to keep
  // "up" meaning "better" across every chart on the page.
  lowerIsBetter?: boolean;
}) {
  const points = values.filter(
    (value): value is number =>
      typeof value === "number" && Number.isFinite(value),
  );
  if (points.length < 2) {
    return (
      <span className="sparkline-empty" role="status">
        Yetersiz veri
      </span>
    );
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const coordinates = points.map((value, index) => {
    const normalized = ((value - min) / span) * (height - 4) + 2;
    const y = lowerIsBetter ? normalized : height - normalized;
    return `${(index * step).toFixed(1)},${y.toFixed(1)}`;
  });
  const last = points[points.length - 1] ?? min;
  return (
    <svg
      className="sparkline"
      role="img"
      aria-label={`${label}: ${points.length} nokta, son değer ${last}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={coordinates.join(" ")}
      />
    </svg>
  );
}
