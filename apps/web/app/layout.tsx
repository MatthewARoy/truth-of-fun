import type { ReactNode } from "react";
import "./globals.css";
import { SiteNav } from "@/components/site-nav";
import { AuthProvider } from "@/lib/auth-context";

export const metadata = {
  title: "Truth of Fun",
  description: "Find something fun to do",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <main className="page-shell">
            <header className="space-y-3">
              <div className="space-y-1">
                <h1 className="text-2xl font-semibold">Truth of Fun</h1>
                <p className="text-sm text-slate-400">Find something fun to do</p>
              </div>
              <SiteNav />
            </header>
            {children}
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
