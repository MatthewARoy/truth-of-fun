"use client";

import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from "react";
import { apiClient } from "@/lib/api/client";

type AuthState = {
  token: string | null;
  email: string | null;
  userId: number | null;
  ready: boolean;
};

type AuthContextValue = AuthState & {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const STORAGE_KEY = "tof_auth";

export function AuthProvider({ children }: { children: ReactNode }) {
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

  const persist = useCallback((token: string, email: string, userId: number) => {
    apiClient.setToken(token);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, email, userId }));
    setState({ token, email, userId, ready: true });
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiClient.login({ email, password });
    persist(res.access_token, res.email, res.user_id);
  }, [persist]);

  const register = useCallback(async (email: string, password: string) => {
    const res = await apiClient.register({ email, password });
    persist(res.access_token, res.email, res.user_id);
  }, [persist]);

  const logout = useCallback(() => {
    apiClient.setToken(null);
    localStorage.removeItem(STORAGE_KEY);
    setState({ token: null, email: null, userId: null, ready: true });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
}
