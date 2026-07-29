import {
  ArrowRight,
  AudioLines,
  Captions,
  Clapperboard,
  Download,
  Inbox,
  ShieldAlert,
  Sparkles,
  X,
  type LucideIcon,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { useAuth } from "../lib/auth";
import {
  TOOLS,
  canUseTool,
  type ToolDefinition,
  type ToolKey,
} from "../lib/permissions";

const TOOL_ICONS: Record<ToolKey, LucideIcon> = {
  douyin_transcribe: AudioLines,
  douyin_download: Download,
  subtitle_workspace: Captions,
  prohibited_word_check: ShieldAlert,
  script_analysis: Clapperboard,
};

function ToolCard({ tool }: { tool: ToolDefinition }) {
  const Icon = TOOL_ICONS[tool.key];
  return (
    <article className={`tool-card ${tool.featured ? "featured" : ""}`}>
      <div className="tool-card-topline">
        <span className="tool-icon">
          <Icon size={tool.featured ? 25 : 21} aria-hidden="true" />
        </span>
        {tool.featured && (
          <span className="tool-recommended">
            <Sparkles size={12} aria-hidden="true" /> 推荐工作流
          </span>
        )}
      </div>
      <div className="tool-card-copy">
        <h2>{tool.title}</h2>
        <p>{tool.description}</p>
      </div>
      <dl className="tool-io">
        <div>
          <dt>输入</dt>
          <dd>{tool.input}</dd>
        </div>
        <span aria-hidden="true">→</span>
        <div>
          <dt>得到</dt>
          <dd>{tool.output}</dd>
        </div>
      </dl>
      <Link to={tool.path} className="tool-enter">
        开始使用 <ArrowRight size={16} aria-hidden="true" />
      </Link>
    </article>
  );
}

export function ToolsPage() {
  const { user } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as
    | { accessDenied?: boolean; from?: string }
    | null;
  const availableTools = TOOLS.filter((tool) => canUseTool(user, tool));
  const videoTools = availableTools.filter((tool) => tool.group === "video");
  const copyTools = availableTools.filter((tool) => tool.group === "copy");

  function dismissNotice() {
    navigate(location.pathname, { replace: true, state: null });
  }

  return (
    <AppShell>
      <div className="tools-page">
        <section className="tools-hero">
          <span className="eyebrow">CREATIVE TOOLBOX</span>
          <h1>今天想处理什么？</h1>
          <p>从素材到成稿，选择一个工具就可以开始。</p>
        </section>

        {state?.accessDenied && (
          <div className="tools-access-notice" role="status">
            <ShieldAlert size={18} aria-hidden="true" />
            <div>
              <strong>这个工具尚未向你的账号开放</strong>
              <span>已为你返回工具中心，你仍可使用下方已开放的功能。</span>
            </div>
            <button type="button" onClick={dismissNotice} aria-label="关闭提示">
              <X size={17} />
            </button>
          </div>
        )}

        {availableTools.length ? (
          <div className="tool-groups">
            {videoTools.length > 0 && (
              <section className="tool-group" aria-labelledby="video-tools-title">
                <div className="tool-group-heading">
                  <span>01</span>
                  <div>
                    <h2 id="video-tools-title">视频处理</h2>
                    <p>下载、转写与逐句校对</p>
                  </div>
                </div>
                <div className="tool-grid">
                  {videoTools.map((tool) => (
                    <ToolCard key={tool.key} tool={tool} />
                  ))}
                </div>
              </section>
            )}

            {copyTools.length > 0 && (
              <section className="tool-group" aria-labelledby="copy-tools-title">
                <div className="tool-group-heading">
                  <span>02</span>
                  <div>
                    <h2 id="copy-tools-title">文案与合规</h2>
                    <p>检查风险，找到好内容的结构</p>
                  </div>
                </div>
                <div className="tool-grid">
                  {copyTools.map((tool) => (
                    <ToolCard key={tool.key} tool={tool} />
                  ))}
                </div>
              </section>
            )}
          </div>
        ) : (
          <section className="tools-empty">
            <span>
              <Inbox size={30} aria-hidden="true" />
            </span>
            <h2>工具箱还在等待解锁</h2>
            <p>
              你的账号可以浏览每日热榜，但暂时没有可用工具。请联系管理员分配权限。
            </p>
            <Link to="/">返回每日热榜</Link>
          </section>
        )}
      </div>
    </AppShell>
  );
}
