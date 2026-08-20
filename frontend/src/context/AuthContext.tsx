import { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { ReactNode } from "react";
import type { MeResponse, LoginResponse } from "@/types/api";
import { api, ApiClientError } from "@/lib/api";

interface AuthState {
  user: MeResponse | null;
  loginResponse: LoginResponse | null;
  loading: boolean;
  needsMfa: boolean;
  needsMfaEnrolment: boolean;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  setMfaDone: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    loginResponse: null,
    loading: true,
    needsMfa: false,
    needsMfaEnrolment: false,
  });

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.me();
      setState((s) => ({
        ...s,
        user: me,
        loading: false,
        needsMfa: false,
        needsMfaEnrolment: false,
        loginResponse: null,
      }));
    } catch {
      setState((s) => ({
        ...s,
        user: null,
        loading: false,
        needsMfa: false,
        needsMfaEnrolment: false,
      }));
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const login = useCallback(async (email: string, password: string) => {
    const resp = await api.auth.login({ email, password });
    if (resp.mfaRequired) {
      setState((s) => ({
        ...s,
        loginResponse: resp,
        needsMfa: true,
        needsMfaEnrolment: resp.mfaEnrolmentRequired ?? false,
      }));
    } else {
      const me = await api.me();
      setState((s) => ({
        ...s,
        user: me,
        loginResponse: resp,
        needsMfa: false,
        needsMfaEnrolment: false,
      }));
    }
    return resp;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch {
      // ignore
    }
    setState({
      user: null,
      loginResponse: null,
      loading: false,
      needsMfa: false,
      needsMfaEnrolment: false,
    });
  }, []);

  const setMfaDone = useCallback(() => {
    refreshUser();
  }, [refreshUser]);

  return (
    <AuthContext.Provider
      value={{ ...state, login, logout, setMfaDone, refreshUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
