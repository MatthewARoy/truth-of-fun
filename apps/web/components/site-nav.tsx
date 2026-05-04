"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { useAuth } from "@/lib/auth-context";

const links = [
  { href: "/explore", label: "Explore" },
  { href: "/planner", label: "Plan Something" },
  { href: "/recommendations", label: "For You" },
];

export function SiteNav() {
  const pathname = usePathname();
  const { token, email, logout } = useAuth();

  return (
    <nav className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-4">
      {links.map((link) => {
        const isActive = pathname.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "rounded-ui px-3 py-2 text-sm transition",
              isActive ? "bg-brand-500/30 text-brand-100" : "text-slate-300 hover:bg-slate-900"
            )}
          >
            {link.label}
          </Link>
        );
      })}
      <div className="ml-auto flex items-center gap-3">
        {token ? (
          <>
            <span className="text-xs text-slate-500">{email}</span>
            <button onClick={logout} className="rounded-ui px-3 py-2 text-sm text-slate-400 hover:bg-slate-900 transition">
              Log out
            </button>
          </>
        ) : (
          <Link
            href="/login"
            className={cn(
              "rounded-ui px-3 py-2 text-sm transition",
              pathname === "/login" ? "bg-brand-500/30 text-brand-100" : "text-slate-300 hover:bg-slate-900"
            )}
          >
            Sign in
          </Link>
        )}
      </div>
    </nav>
  );
}
