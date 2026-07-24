import { Navigate } from "react-router-dom";
import type { PropsWithChildren } from "react";
import { useAuth } from "../lib/auth";

export function ProtectedRoute({ children }: PropsWithChildren) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="page-loader">
        <span className="spinner" />
        正在恢复工作台…
      </div>
    );
  }
  return user ? children : <Navigate to="/login" replace />;
}

