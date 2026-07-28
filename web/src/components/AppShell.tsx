import {
  CheckCircle2,
  Captions,
  Download,
  AudioLines,
  Clapperboard,
  Eye,
  EyeOff,
  KeyRound,
  LogOut,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useState, type FormEvent, type PropsWithChildren } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";
import { defaultPath, hasPermission } from "../lib/permissions";
import { ThemeToggle } from "./ThemeToggle";

export function AppShell({ children }: PropsWithChildren) {
  const { user, setAuth } = useAuth();
  const navigate = useNavigate();
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
        <Link
          to={defaultPath(user)}
          className="brand"
          aria-label="返回工作台"
        >
          <span className="brand-mark">
            <Sparkles size={18} />
          </span>
          <span>
            <strong>不二</strong>
            <small>SUBTITLE &amp; VIDEO STUDIO</small>
          </span>
        </Link>
        <nav className="site-nav" aria-label="主要功能">
          {hasPermission(user, "douyin_download") &&
            hasPermission(user, "subtitle_workspace") && (
              <NavLink to="/douyin-transcribe">
                <AudioLines size={15} />
                <span>抖音转文案</span>
              </NavLink>
            )}
          {hasPermission(user, "douyin_download") && (
            <NavLink to="/douyin">
              <Download size={15} />
              <span>抖音下载</span>
            </NavLink>
          )}
          {hasPermission(user, "subtitle_workspace") && (
            <NavLink to="/subtitle">
              <Captions size={15} />
              <span>字幕校对</span>
            </NavLink>
          )}
          {hasPermission(user, "prohibited_word_check") && (
            <NavLink to="/prohibited-words">
              <ShieldAlert size={15} />
              <span>违禁词检测</span>
            </NavLink>
          )}
          {hasPermission(user, "script_analysis") && (
            <NavLink to="/script-analysis">
              <Clapperboard size={15} />
              <span>脚本拆解</span>
            </NavLink>
          )}
        </nav>
        <div className="account">
          <span className="account-name">{user?.username}</span>
          <ThemeToggle compact />
          <button
            className="icon-button"
            type="button"
            onClick={() => setPasswordOpen(true)}
            aria-label="修改密码"
            title="修改密码"
          >
            <KeyRound size={18} />
          </button>
          <button className="icon-button" onClick={logout} aria-label="退出登录">
            <LogOut size={18} />
          </button>
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
