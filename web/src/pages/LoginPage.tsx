import { ArrowRight, LockKeyhole, MonitorDown, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { defaultPath } from "../lib/permissions";
import { ThemeToggle } from "../components/ThemeToggle";

export function LoginPage({ adminMode = false }: { adminMode?: boolean }) {
  const { user, setAuth } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={adminMode ? "/" : defaultPath(user)} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.login(username, password);
      setAuth(result);
      navigate(adminMode ? "/" : defaultPath(result.user));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <div className="login-theme-toggle">
        <ThemeToggle />
      </div>
      <section className="login-story">
        <div className="eyebrow">
          {adminMode ? "SECURE · ISOLATED · CONTROLLED" : "PRIVATE · LOCAL · PRECISE"}
        </div>
        {adminMode ? (
          <>
            <h1>
              管理账号，
              <br />
              <em>从独立后台开始。</em>
            </h1>
            <p>仅管理员可以进入，普通访问账号无法查看或创建其他用户。</p>
          </>
        ) : (
          <>
            <h1>
              让每一句话，
              <br />
              <em>准确落在时间里。</em>
            </h1>
            <p>
              先让你信任的 AI 在本机生成 SRT，网站只负责字幕校对、保存和导出。
            </p>
          </>
        )}
        <div className="trust-grid">
          <div>
            {adminMode ? <ShieldCheck size={20} /> : <MonitorDown size={20} />}
            <span>{adminMode ? "管理员限定" : "通用 AI 工具"}</span>
          </div>
          <div>
            <ShieldCheck size={20} />
            <span>{adminMode ? "独立子域名" : "视频不上云"}</span>
          </div>
          <div>
            <LockKeyhole size={20} />
            <span>账号隔离</span>
          </div>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <div className="login-logo">芦</div>
          <h2>{adminMode ? "进入管理后台" : "进入不二"}</h2>
          <p>
            {adminMode
              ? "请使用管理员账号登录"
              : "使用管理员为你创建的账号登录"}
          </p>
          <form onSubmit={submit}>
            <label>
              用户名
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                placeholder="请输入用户名"
                required
              />
            </label>
            <label>
              密码
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                placeholder="至少 8 位"
                required
              />
            </label>
            {error && <div className="form-error">{error}</div>}
            <button className="primary-button full" disabled={busy}>
              {busy ? "正在登录…" : "登录"}
              {!busy && <ArrowRight size={18} />}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
