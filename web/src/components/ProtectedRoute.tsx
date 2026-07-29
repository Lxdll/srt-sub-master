import { Navigate, useLocation } from "react-router-dom";
import type { PropsWithChildren } from "react";
import { useAuth } from "../lib/auth";
import { hasPermission } from "../lib/permissions";
import type { PermissionKey } from "../types";

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

export function FeatureRoute({
  children,
  permission,
}: PropsWithChildren<{ permission: PermissionKey }>) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="page-loader">
        <span className="spinner" />
        正在恢复工作台…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return hasPermission(user, permission) ? (
    children
  ) : (
    <Navigate
      to="/tools"
      replace
      state={{ accessDenied: true, from: location.pathname }}
    />
  );
}

export function MultiFeatureRoute({
  children,
  permissions,
}: PropsWithChildren<{ permissions: PermissionKey[] }>) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="page-loader">
        <span className="spinner" />
        正在恢复工作台…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return permissions.every((permission) => hasPermission(user, permission)) ? (
    children
  ) : (
    <Navigate
      to="/tools"
      replace
      state={{ accessDenied: true, from: location.pathname }}
    />
  );
}
