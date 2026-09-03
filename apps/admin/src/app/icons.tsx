import type { SVGProps } from "react";

export type AppIconName =
  | "activity"
  | "agents"
  | "analytics"
  | "approval"
  | "arrow-left"
  | "bell"
  | "brief"
  | "chevron-down"
  | "content"
  | "distribution"
  | "draft"
  | "health"
  | "history"
  | "home"
  | "motor"
  | "plus"
  | "published"
  | "queue"
  | "research"
  | "search"
  | "settings"
  | "source"
  | "spark";

type IconProps = Omit<SVGProps<SVGSVGElement>, "name"> & {
  name: AppIconName;
  size?: number;
};

function IconPaths({ name }: { name: AppIconName }) {
  switch (name) {
    case "home":
      return (
        <>
          <path d="m3 11 9-7 9 7" />
          <path d="M5 10v10h14V10" />
          <path d="M9 20v-6h6v6" />
        </>
      );
    case "activity":
      return (
        <>
          <rect x="3" y="5" width="18" height="14" rx="3" />
          <path d="M7 12h2l2-4 3 8 2-4h2" />
        </>
      );
    case "history":
      return (
        <>
          <path d="M4 12a8 8 0 1 0 2.34-5.66L4 8.68" />
          <path d="M4 4v4.68h4.68" />
          <path d="M12 8v5l3 2" />
        </>
      );
    case "source":
      return (
        <>
          <rect x="3" y="4" width="18" height="16" rx="3" />
          <path d="M7 8h4M7 12h10M7 16h7" />
          <circle cx="17" cy="8" r="1" />
        </>
      );
    case "spark":
      return (
        <>
          <path d="m12 3 1.4 4.6L18 9l-4.6 1.4L12 15l-1.4-4.6L6 9l4.6-1.4Z" />
          <path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7Z" />
        </>
      );
    case "content":
      return (
        <>
          <path d="M6 3h9l4 4v14H6z" />
          <path d="M15 3v5h4M9 12h7M9 16h7" />
        </>
      );
    case "brief":
      return (
        <>
          <rect x="5" y="4" width="14" height="17" rx="2" />
          <path d="M9 4V2h6v2M9 9h6M9 13h6M9 17h4" />
        </>
      );
    case "draft":
      return (
        <>
          <path d="M4 20h4l11-11-4-4L4 16z" />
          <path d="m13.5 6.5 4 4M4 4h6" />
        </>
      );
    case "approval":
      return (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="m8 12 2.5 2.5L16 9" />
        </>
      );
    case "queue":
      return (
        <>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M7 9h10M7 13h7M7 17h4" />
        </>
      );
    case "published":
      return (
        <>
          <path d="M5 19h14V8l-5-5H5z" />
          <path d="M14 3v5h5M8 14l2 2 5-5" />
        </>
      );
    case "distribution":
      return (
        <>
          <circle cx="5" cy="12" r="2" />
          <circle cx="19" cy="6" r="2" />
          <circle cx="19" cy="18" r="2" />
          <path d="m7 11 10-4M7 13l10 4" />
        </>
      );
    case "agents":
      return (
        <>
          <circle cx="12" cy="7" r="3" />
          <circle cx="5" cy="16" r="2" />
          <circle cx="19" cy="16" r="2" />
          <path d="M12 10v3M7 16h10M5 14v-2h14v2" />
        </>
      );
    case "motor":
      return (
        <>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
        </>
      );
    case "research":
      return (
        <>
          <circle cx="10" cy="10" r="6" />
          <path d="m14.5 14.5 5 5M8 10h4M10 8v4" />
        </>
      );
    case "health":
      return (
        <>
          <path d="M3 12h4l2-5 4 10 2-5h6" />
          <path d="M4 5a9 9 0 1 1-1 10" />
        </>
      );
    case "settings":
      return (
        <>
          <circle cx="12" cy="12" r="3" />
          <path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A7 7 0 0 0 15 6l-.3-2.6h-4L10.4 6A7 7 0 0 0 9 7.1l-2.4-1-2 3.4L6.7 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1A7 7 0 0 0 10.5 18l.3 2.6h4L15 18a7 7 0 0 0 1.4-1.1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .2-1Z" />
        </>
      );
    case "analytics":
      return (
        <>
          <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
        </>
      );
    case "arrow-left":
      return (
        <>
          <path d="m15 18-6-6 6-6" />
          <path d="M9 12h11" />
        </>
      );
    case "search":
      return (
        <>
          <circle cx="11" cy="11" r="7" />
          <path d="m16 16 5 5" />
        </>
      );
    case "bell":
      return (
        <>
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
          <path d="M10 21h4" />
        </>
      );
    case "chevron-down":
      return <path d="m7 9 5 5 5-5" />;
    case "plus":
      return (
        <>
          <path d="M12 5v14M5 12h14" />
        </>
      );
    default:
      return (
        <>
          <rect x="4" y="4" width="16" height="16" rx="4" />
          <path d="M8 12h8M12 8v8" />
        </>
      );
  }
}

export function AppIcon({ name, size = 18, className, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      focusable="false"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      {...props}
    >
      <IconPaths name={name} />
    </svg>
  );
}

export function ContentOsMark() {
  return (
    <span className="contentos-mark" aria-hidden="true">
      <svg viewBox="0 0 40 40" role="presentation">
        <path d="M20 3 34 11v18L20 37 6 29V11Z" />
        <path d="m27 14-7-4-7 4v12l7 4 7-4" />
        <path d="m24 17-4-2-4 2v6l4 2 4-2" />
      </svg>
    </span>
  );
}
