import type { Metadata } from "next";
import type { ReactNode } from "react";

import { logoutAction } from "./login/actions";
import { AppNav } from "./nav";

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
          <div className="app-identity">
            <span className="app-name">ContentOS</span>
            <span className="app-role">Internal Control Panel</span>
          </div>
          <AppNav />
          <form action={logoutAction}>
            <button type="submit">Sign out</button>
          </form>
        </header>
        <main className="app-main">{children}</main>
      </body>
    </html>
  );
}
