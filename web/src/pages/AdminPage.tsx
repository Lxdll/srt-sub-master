import {
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  LogOut,
  Save,
  ShieldAlert,
  ShieldCheck,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  FEATURE_LABELS,
  FEATURE_PERMISSIONS,
} from "../lib/permissions";
import type { AdminUser, PermissionKey } from "../types";
import { ThemeToggle } from "../components/ThemeToggle";

function formatCreatedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function PermissionEditor({ item }: { item: AdminUser }) {
  const queryClient = useQueryClient();
  const [permissions, setPermissions] = useState<PermissionKey[]>(
    item.permissions,
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => setPermissions(item.permissions), [item.permissions]);

  function toggle(permission: PermissionKey) {
    setMessage("");
    setPermissions((current) =>
      current.includes(permission)
        ? current.filter((item) => item !== permission)
        : [...current, permission],
    );
  }

  async function save() {
    setBusy(true);
    setMessage("");
    try {
      await api.updateUserPermissions(item.id, permissions);
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setMessage("权限已保存");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "权限保存失败");
    } finally {
      setBusy(false);
    }
  }

  if (item.is_admin) {
    return (
      <div className="permission-admin-note">
        <ShieldCheck size={15} /> 管理员默认拥有全部功能权限
      </div>
    );
  }

  const unchanged =
    [...permissions].sort().join(",") ===
    [...item.permissions].sort().join(",");

  return (
    <div className="permission-editor">
      <div className="permission-options">
        {FEATURE_PERMISSIONS.map((permission) => (
          <label key={permission}>
            <input
              type="checkbox"
              checked={permissions.includes(permission)}
              onChange={() => toggle(permission)}
            />
            <span>{FEATURE_LABELS[permission]}</span>
          </label>
        ))}
      </div>
      <div className="permission-actions">
        {message && <small>{message}</small>}
        <button type="button" onClick={save} disabled={busy || unchanged}>
          <Save size={15} />
          {busy ? "保存中…" : "保存权限"}
        </button>
      </div>
    </div>
  );
}

type PasswordDialog =
  | { kind: "self"; username: string }
  | { kind: "reset"; userId: string; username: string };

export function AdminPage() {
  const { user, setAuth } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showCreatePassword, setShowCreatePassword] = useState(false);
  const [permissions, setPermissions] = useState<PermissionKey[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);
  const [passwordDialog, setPasswordDialog] =
    useState<PasswordDialog | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: api.adminUsers,
    enabled: Boolean(user?.is_admin),
  });

  async function logout() {
    await api.logout();
    setAuth(null);
    navigate("/login");
  }

  function toggleCreatePermission(permission: PermissionKey) {
    setPermissions((current) =>
      current.includes(permission)
        ? current.filter((item) => item !== permission)
        : [...current, permission],
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await api.createUser(username.trim(), password, permissions);
      setUsername("");
      setPassword("");
      setPermissions([]);
      setShowCreatePassword(false);
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setMessage({ kind: "success", text: "访问账号创建成功。" });
    } catch (reason) {
      setMessage({
        kind: "error",
        text: reason instanceof Error ? reason.message : "账号创建失败。",
      });
    } finally {
      setBusy(false);
    }
  }

  function closePasswordDialog() {
    if (passwordBusy) return;
    setPasswordDialog(null);
    setCurrentPassword("");
    setNewPassword("");
    setShowCurrentPassword(false);
    setShowNewPassword(false);
    setPasswordMessage(null);
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    if (!passwordDialog) return;
    setPasswordBusy(true);
    setPasswordMessage(null);
    try {
      if (passwordDialog.kind === "self") {
        await api.changePassword(currentPassword, newPassword);
      } else {
        await api.resetUserPassword(passwordDialog.userId, newPassword);
      }
      setCurrentPassword("");
      setNewPassword("");
      setPasswordMessage({
        kind: "success",
        text:
          passwordDialog.kind === "self"
            ? "管理员密码修改成功。"
            : "新密码已设置，该账号的原登录已退出。",
      });
    } catch (reason) {
      setPasswordMessage({
        kind: "error",
        text: reason instanceof Error ? reason.message : "密码设置失败。",
      });
    } finally {
      setPasswordBusy(false);
    }
  }

  if (!user?.is_admin) {
    return (
      <main className="admin-denied">
        <div>
          <ShieldAlert size={34} />
          <h1>当前账号没有后台权限</h1>
          <p>请退出后使用管理员账号登录。</p>
          <button className="primary-button" type="button" onClick={logout}>
            <LogOut size={17} /> 退出当前账号
          </button>
        </div>
      </main>
    );
  }

  const regularUserCount =
    users.data?.filter((item) => !item.is_admin).length ?? 0;

  return (
    <div className="admin-app">
      <header className="admin-header">
        <div className="admin-brand">
          <img
            src="/icons/buer-rabbit-96.png"
            alt=""
            width="39"
            height="39"
          />
          <div>
            <strong>不二</strong>
            <small>ADMIN CONSOLE</small>
          </div>
        </div>
        <div className="admin-account">
          <span>
            <ShieldCheck size={15} /> {user.username}
          </span>
          <ThemeToggle compact />
          <button
            type="button"
            onClick={() =>
              setPasswordDialog({ kind: "self", username: user.username })
            }
            aria-label="修改管理员密码"
            title="修改密码"
          >
            <KeyRound size={17} />
          </button>
          <button type="button" onClick={logout} aria-label="退出后台">
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <main className="admin-main">
        <section className="admin-intro">
          <div>
            <span className="eyebrow">ACCOUNT &amp; PERMISSION ADMINISTRATION</span>
            <h1>账号与权限管理</h1>
            <p>为每个账号单独分配功能权限，并可随时重置访问密码。</p>
          </div>
          <div className="admin-stat">
            <Users size={22} />
            <span>访问账号</span>
            <strong>{regularUserCount}</strong>
          </div>
        </section>

        <div className="admin-grid">
          <section className="admin-create-panel">
            <div className="admin-section-heading">
              <span>
                <UserPlus size={18} />
              </span>
              <div>
                <h2>创建访问账号</h2>
                <p>创建时直接选择这个账号可以使用的功能。</p>
              </div>
            </div>
            <form onSubmit={submit}>
              <label>
                用户名
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="off"
                  minLength={3}
                  maxLength={80}
                  placeholder="例如：chen-er"
                  required
                />
              </label>
              <label>
                初始密码
                <div className="admin-password-field">
                  <KeyRound size={16} />
                  <input
                    type={showCreatePassword ? "text" : "password"}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    minLength={8}
                    maxLength={256}
                    placeholder="至少 8 位"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowCreatePassword((value) => !value)}
                    aria-label={showCreatePassword ? "隐藏初始密码" : "查看初始密码"}
                  >
                    {showCreatePassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </div>
              </label>
              <fieldset className="admin-permission-fieldset">
                <legend>功能权限</legend>
                {FEATURE_PERMISSIONS.map((permission) => (
                  <label key={permission}>
                    <input
                      type="checkbox"
                      checked={permissions.includes(permission)}
                      onChange={() => toggleCreatePermission(permission)}
                    />
                    <span>{FEATURE_LABELS[permission]}</span>
                  </label>
                ))}
              </fieldset>
              {message && (
                <div
                  className={`admin-message ${message.kind}`}
                  role={message.kind === "error" ? "alert" : "status"}
                >
                  {message.kind === "success" ? (
                    <CheckCircle2 size={16} />
                  ) : (
                    <ShieldAlert size={16} />
                  )}
                  {message.text}
                </div>
              )}
              <button
                className="primary-button full"
                type="submit"
                disabled={busy || !username.trim() || password.length < 8}
              >
                <UserPlus size={17} />
                {busy ? "正在创建…" : "创建账号"}
              </button>
            </form>
          </section>

          <section className="admin-users-panel">
            <div className="admin-section-heading">
              <span>
                <Users size={18} />
              </span>
              <div>
                <h2>全部账号</h2>
                <p>{users.data?.length ?? 0} 个账号，权限修改即时生效。</p>
              </div>
            </div>
            {users.isLoading ? (
              <div className="admin-list-state">正在读取账号…</div>
            ) : users.isError ? (
              <div className="admin-list-state error">账号列表读取失败。</div>
            ) : (
              <div className="admin-user-list">
                {users.data?.map((item) => (
                  <article className="admin-user-card" key={item.id}>
                    <div className="admin-user-summary">
                      <span className="admin-user-avatar">
                        {item.username.slice(0, 1).toUpperCase()}
                      </span>
                      <div>
                        <strong>{item.username}</strong>
                        <small>{formatCreatedAt(item.created_at)}</small>
                      </div>
                      <span
                        className={item.is_admin ? "admin-role" : "user-role"}
                      >
                        {item.is_admin ? "管理员" : "访问账号"}
                      </span>
                    </div>
                    <PermissionEditor item={item} />
                    {!item.is_admin && (
                      <button
                        className="admin-reset-button"
                        type="button"
                        onClick={() =>
                          setPasswordDialog({
                            kind: "reset",
                            userId: item.id,
                            username: item.username,
                          })
                        }
                      >
                        <KeyRound size={15} /> 重置密码
                      </button>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>

      {passwordDialog && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closePasswordDialog();
          }}
        >
          <section
            className="password-dialog admin-password-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-password-title"
          >
            <div className="dialog-heading">
              <div>
                <span>
                  <KeyRound size={18} />
                </span>
                <div>
                  <h2 id="admin-password-title">
                    {passwordDialog.kind === "self"
                      ? "修改管理员密码"
                      : `重置 ${passwordDialog.username} 的密码`}
                  </h2>
                  <p>
                    {passwordDialog.kind === "self"
                      ? "修改后，其他设备上的管理员登录会退出。"
                      : "保存后，该账号需要使用新密码重新登录。"}
                  </p>
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
            <form onSubmit={savePassword}>
              {passwordDialog.kind === "self" && (
                <label>
                  当前密码
                  <div className="password-input">
                    <input
                      type={showCurrentPassword ? "text" : "password"}
                      value={currentPassword}
                      onChange={(event) =>
                        setCurrentPassword(event.target.value)
                      }
                      autoComplete="current-password"
                      required
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setShowCurrentPassword((value) => !value)
                      }
                      aria-label={
                        showCurrentPassword ? "隐藏当前密码" : "查看当前密码"
                      }
                    >
                      {showCurrentPassword ? (
                        <EyeOff size={17} />
                      ) : (
                        <Eye size={17} />
                      )}
                    </button>
                  </div>
                </label>
              )}
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
                  newPassword.length < 8 ||
                  (passwordDialog.kind === "self" && !currentPassword)
                }
              >
                {passwordBusy ? "正在保存…" : "保存新密码"}
              </button>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
