import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  api,
  onSessionEnded,
  post,
  refreshSession,
  takeRefreshedSession,
  tokenStore,
  type SessionPayload,
} from "@/lib/api";
import { common } from "@/copy/common";

export type AuthUser = SessionPayload["user"];
export type AuthTenant = SessionPayload["tenant"];

type AuthState =
  | { status: "loading" }
  | { status: "anonymous"; expired: boolean }
  | { status: "authenticated"; user: AuthUser; tenant: AuthTenant };

type AuthContextValue = {
  state: AuthState;
  login: (email: string, password: string) => Promise<void>;
  demoLogin: (profileKey: string) => Promise<void>;
  logout: () => Promise<void>;
  logoutEverywhere: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function toAuthenticated(payload: SessionPayload): AuthState {
  tokenStore.set(payload.access_token);
  return { status: "authenticated", user: payload.user, tenant: payload.tenant };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const queryClient = useQueryClient();

  // Restore the session from the refresh cookie on load.
  useEffect(() => {
    let active = true;
    void refreshSession().then((ok) => {
      if (!active) return;
      const payload = ok ? takeRefreshedSession() : null;
      setState(payload ? toAuthenticated(payload) : { status: "anonymous", expired: false });
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    onSessionEnded(() => {
      tokenStore.set(null);
      queryClient.clear();
      setState({ status: "anonymous", expired: true });
    });
    return () => onSessionEnded(null);
  }, [queryClient]);

  const login = useCallback(async (email: string, password: string) => {
    const payload = await api<SessionPayload>("/auth/login", {
      method: "POST",
      body: { email, password },
      anonymous: true,
      retryOnTimeout: true,
    });
    setState(toAuthenticated(payload));
  }, []);

  const demoLogin = useCallback(async (profileKey: string) => {
    const payload = await api<SessionPayload>("/auth/demo-login", {
      method: "POST",
      body: { profile_key: profileKey },
      anonymous: true,
      retryOnTimeout: true,
    });
    setState(toAuthenticated(payload));
  }, []);

  const finishLogout = useCallback(() => {
    tokenStore.set(null);
    queryClient.clear();
    setState({ status: "anonymous", expired: false });
  }, [queryClient]);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", {
        method: "POST",
        body: {},
        anonymous: true,
        headers: { "X-Requested-With": "backroom" },
      });
    } finally {
      finishLogout();
    }
  }, [finishLogout]);

  const logoutEverywhere = useCallback(async () => {
    try {
      await post("/auth/logout-all");
    } finally {
      finishLogout();
    }
  }, [finishLogout]);

  const value = useMemo(
    () => ({ state, login, demoLogin, logout, logoutEverywhere }),
    [state, login, demoLogin, logout, logoutEverywhere],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

/** The signed in user and business. Only call this below `RequireAuth`. */
export function useSession(): { user: AuthUser; tenant: AuthTenant } {
  const { state } = useAuth();
  if (state.status !== "authenticated") throw new Error("No active session");
  return { user: state.user, tenant: state.tenant };
}

/** Route guard: sends signed out visitors to /login and remembers where they were going. */
export function RequireAuth() {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") {
    return (
      <div className="p-6 text-sm text-text-3" role="status">
        {common.loading}
      </div>
    );
  }
  if (state.status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location, expired: state.expired }} />;
  }
  return <Outlet />;
}

/** Keeps signed in people off the login page. */
export function RedirectIfSignedIn({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "authenticated") {
    const from = (location.state as { from?: { pathname: string; search?: string } } | null)?.from;
    return <Navigate to={from ? `${from.pathname}${from.search ?? ""}` : "/"} replace />;
  }
  return <>{children}</>;
}
