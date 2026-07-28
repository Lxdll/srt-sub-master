import { ShieldAlert } from "lucide-react";
import { AppShell } from "../components/AppShell";

export function NoAccessPage() {
  return (
    <AppShell>
      <section className="no-access-page">
        <div>
          <span className="no-access-icon">
            <ShieldAlert size={26} />
          </span>
          <p className="eyebrow">ACCESS PENDING</p>
          <h1>尚未分配功能权限</h1>
          <p>你的账号可以正常登录，但还不能使用具体功能。请联系管理员分配权限。</p>
        </div>
      </section>
    </AppShell>
  );
}
