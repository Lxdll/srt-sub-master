import {
  CheckCircle2,
  CircleAlert,
  Download,
  Laptop,
  RefreshCw,
  Unplug,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { agent } from "../lib/agent";
import type { LocalHealth, LocalSystem, ModelInfo } from "../types";

interface AgentSetupProps {
  onReady: (health: LocalHealth, system: LocalSystem) => void;
}

export function AgentSetup({ onReady }: AgentSetupProps) {
  const [health, setHealth] = useState<LocalHealth | null>(null);
  const [system, setSystem] = useState<LocalSystem | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const [pairCode, setPairCode] = useState("");
  const [pairing, setPairing] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  async function check() {
    setChecking(true);
    setError("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 2500);
    try {
      const result = await agent.health(controller.signal);
      setHealth(result);
      if (result.paired) {
        const localSystem = await agent.system();
        setSystem(localSystem);
        onReady(result, localSystem);
      }
    } catch {
      setHealth(null);
    } finally {
      clearTimeout(timeout);
      setChecking(false);
    }
  }

  useEffect(() => {
    void check();
    const timer = window.setInterval(() => {
      if (health?.paired) {
        agent.system().then((next) => {
          setSystem(next);
          onReady(health, next);
        });
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [health?.paired]);

  async function createPairCode() {
    setPairing(true);
    setError("");
    try {
      const result = await api.pairCode();
      setPairCode(result.code);
      await agent.pair(window.location.origin, window.location.origin, result.code);
      await check();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "配对失败");
    } finally {
      setPairing(false);
    }
  }

  async function download(model: ModelInfo) {
    if (!health?.device_id) return;
    setDownloading(model.id);
    setError("");
    try {
      const { token } = await api.commandToken(health.device_id);
      await agent.downloadModel(model.id, token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型下载失败");
      setDownloading(null);
    }
  }

  if (checking) {
    return (
      <section className="agent-card checking">
        <span className="spinner" />
        <div>
          <strong>正在检查这台电脑</strong>
          <p>确认本机识别器和模型状态…</p>
        </div>
      </section>
    );
  }

  if (!health) {
    return (
      <section className="agent-card disconnected">
        <div className="agent-icon">
          <Unplug size={25} />
        </div>
        <div className="agent-main">
          <span className="status-kicker">尚未连接</span>
          <h2>先安装本机识别器</h2>
          <p>
            它负责在你的电脑上保存视频和运行模型。Linux 服务器不会收到视频内容。
          </p>
          <div className="agent-actions">
            <a className="primary-button" href="/downloads/srt-sub-agent-macos-arm64.dmg">
              <Download size={17} />
              下载 Mac 版
            </a>
            <a className="secondary-button" href="/downloads/srt-sub-agent-windows-x64.exe">
              <Download size={17} />
              下载 Windows 版
            </a>
            <button className="text-button" onClick={check}>
              <RefreshCw size={16} />
              已安装，重新检测
            </button>
          </div>
          <small className="permission-note">
            Chrome / Edge 可能询问“访问本地网络”，请选择允许。
          </small>
          <ol className="install-steps">
            <li>下载对应安装包并完成安装。</li>
            <li>首次打开如遇安全提示，确认允许运行。</li>
            <li>保持识别器运行，回到这里点击“重新检测”。</li>
          </ol>
        </div>
      </section>
    );
  }

  if (!health.paired) {
    return (
      <section className="agent-card pairing">
        <div className="agent-icon">
          <Laptop size={25} />
        </div>
        <div className="agent-main">
          <span className="status-kicker">识别器已运行</span>
          <h2>将这台电脑与账号配对</h2>
          <p>配对后，只有当前账号可以向这台电脑发送识别任务。</p>
          {pairCode && <div className="pair-code">{pairCode}</div>}
          {error && <div className="form-error">{error}</div>}
          <button
            className="primary-button"
            onClick={createPairCode}
            disabled={pairing}
          >
            {pairing ? "正在配对…" : "生成配对码并连接"}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="agent-card ready">
      <div className="agent-icon success">
        <CheckCircle2 size={25} />
      </div>
      <div className="agent-main">
        <div className="agent-ready-line">
          <div>
            <span className="status-kicker">本机识别器已连接</span>
            <h2>{system?.hardware.hostname || "当前电脑"}</h2>
          </div>
          <span className="hardware-pill">
            {system?.hardware.platform} · {system?.hardware.memory_gb ?? "—"}GB
          </span>
        </div>
        <div className="model-list">
          {system?.models.map((model) => {
            const progress = model.download;
            return (
              <div className="model-row" key={model.id}>
                <div>
                  <strong>
                    {model.label}
                    {model.recommended && <span className="recommend">推荐</span>}
                  </strong>
                  <p>{model.description}</p>
                </div>
                {model.installed || progress?.status === "ready" ? (
                  <span className="installed">
                    <CheckCircle2 size={15} />
                    已安装
                  </span>
                ) : progress?.status === "downloading" ||
                  progress?.status === "queued" ? (
                  <div className="mini-progress">
                    <span style={{ width: `${progress?.progress ?? 2}%` }} />
                  </div>
                ) : (
                  <button
                    className="small-button"
                    onClick={() => download(model)}
                  >
                    {progress?.status === "failed" ? "重试" : "下载"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
        {error && (
          <div className="inline-warning">
            <CircleAlert size={16} />
            {error}
          </div>
        )}
        {system?.models.some((model) => model.download?.status === "failed") && (
          <div className="inline-warning">
            <CircleAlert size={16} />
            模型下载失败，请检查网络与磁盘空间后重试。
          </div>
        )}
      </div>
    </section>
  );
}
