"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import type { AuthResponse } from "@truth-of-fun/api-client";
import { apiClient } from "@/lib/api/client";
import { safeReturnPath } from "@/lib/return-path";

type AuthState = {
  token: string | null;
  email: string | null;
  userId: number | null;
  ready: boolean;
};

type AuthContextValue = AuthState & {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  /** Adopt a login-shaped response (password reset, password change). */
  setSession: (response: AuthResponse) => void;
  /** Forget the session in this browser. */
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = "tof_auth";
const SIGNED_OUT: AuthState = { token: null, email: null, userId: null, ready: true };

function clearStoredSession() {
  apiClient.setToken(null);
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode); the in-memory session is still cleared.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<AuthState>({
    token: null,
    email: null,
    userId: null,
    ready: false,
  });

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw);
        if (saved.token) {
          apiClient.setToken(saved.token);
          setState({ token: saved.token, email: saved.email, userId: saved.userId, ready: true });
          return;
        }
      }
    } catch {}
    setState((s) => ({ ...s, ready: true }));
  }, []);

  // The API rejected the stored token (expired, revoked, or the account is
  // gone). Keeping it would make every later request fail the same way, so
  // drop the session and send the user to sign in, returning them to where
  // they were. Failed sign-in attempts never reach this handler.
  useEffect(() => {
    apiClient.setUnauthorizedHandler(() => {
      clearStoredSession();
      setState(SIGNED_OUT);
      const { pathname, search, hash } = window.location;
      if (pathname === "/login") return;
      const next = safeReturnPath(`${pathname}${search}${hash}`);
      router.replace(`/login?reason=expired&next=${encodeURIComponent(next)}`);
    });
    return () => apiClient.setUnauthorizedHandler(null);
  }, [router]);

  const persist = useCallback((token: string, email: string, userId: number) => {
    apiClient.setToken(token);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, email, userId }));
    } catch {
      // The session still works for this page load.
    }
    setState({ token, email, userId, ready: true });
  }, []);

  const setSession = useCallback((response: AuthResponse) => {
    persist(response.access_token, response.email, response.user_id);
  }, [persist]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiClient.login({ email, password });
    persist(res.access_token, res.email, res.user_id);
  }, [persist]);

  const register = useCallback(async (email: string, password: string) => {
    const res = await apiClient.register({ email, password });
    persist(res.access_token, res.email, res.user_id);
  }, [persist]);

  const logout = useCallback(() => {
    clearStoredSession();
    setState(SIGNED_OUT);
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, register, setSession, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
}
