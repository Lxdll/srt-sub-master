import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";
import { api } from "./api";
import type { AuthResponse } from "../types";

interface AuthContextValue {
  auth: AuthResponse | null;
  user: AuthResponse["user"] | null;
  loading: boolean;
  setAuth: (value: AuthResponse | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [auth, setAuth] = useState<AuthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setAuth)
      .catch(() => setAuth(null))
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo(
    () => ({ auth, user: auth?.user ?? null, loading, setAuth }),
    [auth, loading],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}

