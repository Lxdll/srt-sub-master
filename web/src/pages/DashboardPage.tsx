import { ArrowUpRight, History, ShieldCheck } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { SrtUploadPanel } from "../components/SrtUploadPanel";
import { TaskList } from "../components/TaskList";
import { api } from "../lib/api";

export function DashboardPage() {
  const queryClient = useQueryClient();
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: api.tasks,
    refetchInterval: 2000,
  });

  return (
    <AppShell>
      <div className="dashboard">
        <section className="dashboard-hero">
          <div>
            <span className="eyebrow">SUBTITLE WORKSPACE</span>
            <h1>今天要校对哪一份字幕？</h1>
            <p>先由任意 AI 在本机生成 SRT，再到这里逐句校对、保存和导出。</p>
          </div>
          <div className="privacy-badge">
            <ShieldCheck size={21} />
            <div>
              <strong>网站只接收字幕</strong>
              <span>视频与模型始终留在本机</span>
            </div>
          </div>
        </section>

        <SrtUploadPanel
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

        <footer className="dashboard-footer">
          <span>不二 · 本机语音识别与字幕校对</span>
          <a href="/api/docs" target="_blank" rel="noreferrer">
            API 文档 <ArrowUpRight size={14} />
          </a>
        </footer>
      </div>
    </AppShell>
  );
}
