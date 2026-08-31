import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, getToken, setToken, setUnauthorizedHandler } from "@/api/client";
import type { MeResponse, TokenResponse } from "@/api/types";

interface AuthState {
  me: MeResponse | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const clearSession = useMemo(
    () => () => {
      setToken(null);
      setMe(null);
      queryClient.clear();
    },
    [queryClient]
  );

  useEffect(() => {
    setUnauthorizedHandler(clearSession);
    return () => setUnauthorizedHandler(null);
  }, [clearSession]);

  // 启动时若有 token，拉 /auth/me 注入全局 AccessContext
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    api
      .get<MeResponse>("/auth/me")
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch(() => {
        if (!cancelled) clearSession();
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  const login = async (username: string, password: string) => {
    const token = await api.form<TokenResponse>(
      "/auth/token",
      new URLSearchParams({ username, password })
    );
    setToken(token.access_token);
    const data = await api.get<MeResponse>("/auth/me");
    setMe(data);
    void queryClient.invalidateQueries();
  };

  const logout = async () => {
    try {
      // 后端仅注册 POST /auth/logout（api/app.py）：DELETE 会 405 且
      // httpOnly 会话 cookie 残留（P7 T1：方法与 cookie 失效对齐）。
      await api.post("/auth/logout");
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
    }
    clearSession();
  };

  const value: AuthState = { me, loading, login, logout };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}