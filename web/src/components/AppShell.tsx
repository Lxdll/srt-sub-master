import { LogOut, Sparkles } from "lucide-react";
import type { PropsWithChildren } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";

export function AppShell({ children }: PropsWithChildren) {
  const { user, setAuth } = useAuth();
  const navigate = useNavigate();

  async function logout() {
    await api.logout();
    setAuth(null);
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <Link to="/" className="brand" aria-label="返回工作台">
          <span className="brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            <strong>字准</strong>
            <small>LOCAL SUBTITLE STUDIO</small>
          </span>
        </Link>
        <div className="account">
          <span className="account-name">{user?.username}</span>
          <button className="icon-button" onClick={logout} aria-label="退出登录">
            <LogOut size={18} />
          </button>
        </div>
      </header>
      <main>{children}</main>
    </div>
  );
}

