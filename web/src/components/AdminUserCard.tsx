import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../lib/api";

export function AdminUserCard() {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      await api.createUser(username, password);
      setMessage("账号已创建");
      setUsername("");
      setPassword("");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "创建失败");
    }
  }

  return (
    <section className="admin-card">
      <button className="admin-toggle" onClick={() => setOpen((value) => !value)}>
        <UserPlus size={18} />
        管理员：创建访问账号
      </button>
      {open && (
        <form onSubmit={submit}>
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="用户名"
            required
          />
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="初始密码（至少 8 位）"
            minLength={8}
            required
          />
          <button className="small-button">创建</button>
          {message && <span>{message}</span>}
        </form>
      )}
    </section>
  );
}

