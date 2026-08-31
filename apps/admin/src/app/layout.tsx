import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "ContentOS Admin",
  description: "Private internal control panel for Konsepthane ContentOS.",
  robots: {
    index: false,
    follow: false,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="app-header">
          <span className="app-name">ContentOS</span>
          <span className="app-role">Internal Control Panel</span>
        </header>
        <main className="app-main">{children}</main>
      </body>
    </html>
  );
}
