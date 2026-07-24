import { ArrowUpRight, History, ShieldCheck } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AgentSetup } from "../components/AgentSetup";
import { AdminUserCard } from "../components/AdminUserCard";
import { AppShell } from "../components/AppShell";
import { TaskList } from "../components/TaskList";
import { UploadPanel } from "../components/UploadPanel";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import type { LocalHealth, LocalSystem } from "../types";

export function DashboardPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [health, setHealth] = useState<LocalHealth | null>(null);
  const [system, setSystem] = useState<LocalSystem | null>(null);
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks,
    refetchInterval: 2000,
  });

  function ready(nextHealth: LocalHealth, nextSystem: LocalSystem) {
    setHealth(nextHealth);
    setSystem(nextSystem);
  }

  return (
    <AppShell>
      <div className="dashboard">
        <section className="dashboard-hero">
          <div>
            <span className="eyebrow">SUBTITLE WORKSPACE</span>
            <h1>今天要校对哪一段声音？</h1>
            <p>视频留在本机，识别交给你的电脑。完成后在这里逐句播放、修改和导出。</p>
          </div>
          <div className="privacy-badge">
            <ShieldCheck size={21} />
            <div>
              <strong>视频不上服务器</strong>
              <span>仅字幕与任务状态同步</span>
            </div>
          </div>
        </section>

        <AgentSetup onReady={ready} />
        <UploadPanel
          health={health}
          system={system}
          onUploaded={() =>
            queryClient.invalidateQueries({ queryKey: ["tasks"] })
          }
        />

        <section className="history-section">
          <div className="section-heading">
            <div>
              <span className="eyebrow">
                <History size={14} /> HISTORY
              </span>
              <h2>字幕任务</h2>
            </div>
            <span className="task-count">{tasks.data?.length ?? 0} 个任务</span>
          </div>
          {tasks.isError ? (
            <div className="form-error">无法读取任务列表</div>
          ) : (
            <TaskList
              tasks={tasks.data ?? []}
              onChanged={() =>
                queryClient.invalidateQueries({ queryKey: ["tasks"] })
              }
            />
          )}
        </section>

        {user?.is_admin && <AdminUserCard />}

        <footer className="dashboard-footer">
          <span>字准 · 本机语音识别与字幕校对</span>
          <a href="/api/docs" target="_blank" rel="noreferrer">
            API 文档 <ArrowUpRight size={14} />
          </a>
        </footer>
      </div>
    </AppShell>
  );
}

