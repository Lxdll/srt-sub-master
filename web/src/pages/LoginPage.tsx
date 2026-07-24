import { ArrowRight, LockKeyhole, MonitorDown, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export function LoginPage() {
  const { user, setAuth } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.login(username, password);
      setAuth(result);
      navigate("/");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-story">
        <div className="eyebrow">PRIVATE · LOCAL · PRECISE</div>
        <h1>
          让每一句话，
          <br />
          <em>准确落在时间里。</em>
        </h1>
        <p>
          视频与模型始终留在你的电脑，网站只保存字幕。播放、校对、修改和导出，在一个安静的工作台里完成。
        </p>
        <div className="trust-grid">
          <div>
            <MonitorDown size={20} />
            <span>本机识别</span>
          </div>
          <div>
            <ShieldCheck size={20} />
            <span>视频不上云</span>
          </div>
          <div>
            <LockKeyhole size={20} />
            <span>账号隔离</span>
          </div>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <div className="login-logo">字</div>
          <h2>进入字幕工作台</h2>
          <p>使用管理员为你创建的账号登录</p>
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

