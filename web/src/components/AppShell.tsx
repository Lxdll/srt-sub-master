import {
  CheckCircle2,
  ChevronDown,
  Eye,
  EyeOff,
  House,
  KeyRound,
  LayoutGrid,
  LogOut,
  UserRound,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type PropsWithChildren,
} from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";
import { ThemeToggle } from "./ThemeToggle";

export function AppShell({ children }: PropsWithChildren) {
  const { user, setAuth } = useAuth();
  const navigate = useNavigate();
  const accountMenuRef = useRef<HTMLDetailsElement>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    function closeAccountMenu(event: PointerEvent) {
      if (
        accountMenuRef.current?.open &&
        !accountMenuRef.current.contains(event.target as Node)
      ) {
        accountMenuRef.current.removeAttribute("open");
      }
    }

    function closeAccountMenuWithKeyboard(event: KeyboardEvent) {
      if (event.key === "Escape" && accountMenuRef.current?.open) {
        accountMenuRef.current.removeAttribute("open");
        accountMenuRef.current.querySelector("summary")?.focus();
      }
    }

    document.addEventListener("pointerdown", closeAccountMenu);
    document.addEventListener("keydown", closeAccountMenuWithKeyboard);
    return () => {
      document.removeEventListener("pointerdown", closeAccountMenu);
      document.removeEventListener("keydown", closeAccountMenuWithKeyboard);
    };
  }, []);

  async function logout() {
    await api.logout();
    setAuth(null);
    navigate("/login");
  }

  function closePasswordDialog() {
    if (passwordBusy) return;
    setPasswordOpen(false);
    setCurrentPassword("");
    setNewPassword("");
    setShowCurrentPassword(false);
    setShowNewPassword(false);
    setPasswordMessage(null);
  }

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordBusy(true);
    setPasswordMessage(null);
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setPasswordMessage({ kind: "success", text: "密码修改成功。" });
    } catch (reason) {
      setPasswordMessage({
        kind: "error",
        text: reason instanceof Error ? reason.message : "密码修改失败。",
      });
    } finally {
      setPasswordBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <Link to="/" className="brand" aria-label="返回每日热榜首页">
          <img
            className="brand-mark"
            src="/icons/buer-rabbit-96.png"
            alt=""
            width="37"
            height="37"
          />
          <span>
            <strong>不二</strong>
            <small>SUBTITLE &amp; VIDEO STUDIO</small>
          </span>
        </Link>
        <nav className="site-nav" aria-label="主要导航">
          <NavLink to="/" end>
            <House size={15} />
            <span>首页</span>
          </NavLink>
          <NavLink to="/tools">
            <LayoutGrid size={15} />
            <span>工具</span>
          </NavLink>
        </nav>
        <div className="account">
          <details ref={accountMenuRef} className="account-menu">
            <summary aria-label={`账号菜单，当前用户 ${user?.username ?? ""}`}>
              <span className="account-avatar" aria-hidden="true">
                {(user?.username || "U").slice(0, 1).toUpperCase()}
              </span>
              <span className="account-name">{user?.username}</span>
              <ChevronDown size={14} aria-hidden="true" />
            </summary>
            <div className="account-dropdown">
              <div className="account-dropdown-head">
                <UserRound size={17} aria-hidden="true" />
                <span>
                  <small>当前账号</small>
                  <strong>{user?.username}</strong>
                </span>
              </div>
              <div className="account-theme-row">
                <span>外观主题</span>
                <ThemeToggle compact />
              </div>
              <button
                type="button"
                onClick={() => {
                  accountMenuRef.current?.removeAttribute("open");
                  setPasswordOpen(true);
                }}
              >
                <KeyRound size={17} aria-hidden="true" />
                修改密码
              </button>
              <button type="button" className="logout-item" onClick={logout}>
                <LogOut size={17} aria-hidden="true" />
                退出登录
              </button>
            </div>
          </details>
        </div>
      </header>
      <main>{children}</main>
      {passwordOpen && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closePasswordDialog();
          }}
        >
          <section
            className="password-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="change-password-title"
          >
            <div className="dialog-heading">
              <div>
                <span>
                  <KeyRound size={18} />
                </span>
                <div>
                  <h2 id="change-password-title">修改密码</h2>
                  <p>修改后，其他设备上的登录会自动退出。</p>
                </div>
              </div>
              <button
                type="button"
                onClick={closePasswordDialog}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <form onSubmit={changePassword}>
              <label>
                当前密码
                <div className="password-input">
                  <input
                    type={showCurrentPassword ? "text" : "password"}
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    autoComplete="current-password"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPassword((value) => !value)}
                    aria-label={showCurrentPassword ? "隐藏当前密码" : "查看当前密码"}
                  >
                    {showCurrentPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </label>
              <label>
                新密码
                <div className="password-input">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={8}
                    maxLength={256}
                    placeholder="至少 8 位"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword((value) => !value)}
                    aria-label={showNewPassword ? "隐藏新密码" : "查看新密码"}
                  >
                    {showNewPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </label>
              {passwordMessage && (
                <div
                  className={`dialog-message ${passwordMessage.kind}`}
                  role={passwordMessage.kind === "error" ? "alert" : "status"}
                >
                  {passwordMessage.kind === "success" && (
                    <CheckCircle2 size={16} />
                  )}
                  {passwordMessage.text}
                </div>
              )}
              <button
                className="primary-button full"
                type="submit"
                disabled={
                  passwordBusy ||
                  !currentPassword ||
                  newPassword.length < 8
                }
              >
                {passwordBusy ? "正在修改…" : "确认修改"}
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
