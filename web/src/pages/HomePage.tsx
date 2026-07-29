import {
  ArrowUpRight,
  CalendarDays,
  CircleAlert,
  Clock3,
  Flame,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import type {
  HotRankItem,
  HotRankPlatform,
  HotRankPlatformKey,
} from "../types";

const PLATFORM_ORDER: HotRankPlatformKey[] = [
  "rednote",
  "douyin",
  "bilibili",
];

const PLATFORM_FALLBACK_NAMES: Record<HotRankPlatformKey, string> = {
  rednote: "小红书",
  douyin: "抖音",
  bilibili: "B站热门",
};

const PLATFORM_MARKS: Record<HotRankPlatformKey, string> = {
  rednote: "RED",
  douyin: "DY",
  bilibili: "B",
};

function formatDate(value: Date) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(value);
}

function formatTime(value: string | null | undefined) {
  if (!value) return "等待更新";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "等待更新";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatHeat(value: HotRankItem["hot_value"]) {
  if (value === null || value === undefined || value === "") return null;
  return typeof value === "number"
    ? new Intl.NumberFormat("zh-CN", { notation: "compact" }).format(value)
    : value;
}

function PlatformCard({
  platform,
  loading = false,
}: {
  platform: HotRankPlatform;
  loading?: boolean;
}) {
  const isStale = platform.status === "stale";
  const isUnavailable = platform.status === "unavailable";
  const items = platform.items.slice(0, 10);

  return (
    <article
      className={`rank-card rank-card-${platform.platform}`}
      aria-labelledby={`rank-${platform.platform}`}
    >
      <header className="rank-card-header">
        <div className="platform-identity">
          <span className="platform-mark" aria-hidden="true">
            {PLATFORM_MARKS[platform.platform]}
          </span>
          <div>
            <h2 id={`rank-${platform.platform}`}>
              {platform.display_name || PLATFORM_FALLBACK_NAMES[platform.platform]}
            </h2>
            <span>今日热榜 · TOP 10</span>
          </div>
        </div>
        <span
          className={`rank-status ${platform.status}`}
          title={
            isStale
              ? "实时数据暂不可用，当前展示最近一次成功快照"
              : platform.source === "uapi"
                ? "主数据源暂不可用，已自动切换备用源"
                : undefined
          }
        >
          <i aria-hidden="true" />
          {isUnavailable
            ? "暂不可用"
            : isStale
              ? "缓存榜单"
              : platform.source === "uapi"
                ? "备用源"
                : "实时"}
        </span>
      </header>

      {loading ? (
        <div className="rank-skeleton" aria-label="正在加载榜单">
          {Array.from({ length: 10 }, (_, index) => (
            <span key={index} aria-hidden="true">
              <i />
              <b />
              <em />
            </span>
          ))}
        </div>
      ) : items.length > 0 ? (
        <ol className="rank-list">
          {items.map((item, index) => {
            const heat = formatHeat(item.hot_value);
            return (
              <li key={`${item.rank}-${item.title}`}>
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={item.title}
                  aria-label={`第 ${item.rank || index + 1} 名：${item.title}，在新标签页打开`}
                >
                  <span
                    className={`rank-number ${index < 3 ? "top" : ""}`}
                    aria-hidden="true"
                  >
                    {String(item.rank || index + 1).padStart(2, "0")}
                  </span>
                  <span className="rank-title">
                    <strong>{item.title}</strong>
                    {(item.badge || heat) && (
                      <small>
                        {item.badge && <em>{item.badge}</em>}
                        {heat && (
                          <span>
                            <Flame size={11} aria-hidden="true" />
                            {heat}
                          </span>
                        )}
                      </small>
                    )}
                  </span>
                  <ArrowUpRight
                    className="rank-link-icon"
                    size={15}
                    aria-hidden="true"
                  />
                </a>
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="rank-empty">
          <CircleAlert size={24} aria-hidden="true" />
          <strong>{isUnavailable ? "榜单暂时走开了" : "今天还没有榜单"}</strong>
          <span>稍后刷新，我们会继续尝试获取。</span>
        </div>
      )}

      <footer>
        <Clock3 size={13} aria-hidden="true" />
        更新于 {formatTime(platform.updated_at)}
      </footer>
    </article>
  );
}

export function HomePage() {
  const queryClient = useQueryClient();
  const [activePlatform, setActivePlatform] =
    useState<HotRankPlatformKey>("rednote");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const ranks = useQuery({
    queryKey: ["hot-ranks"],
    queryFn: () => api.hotRanks(),
    refetchInterval: 15 * 60 * 1000,
  });

  const platforms = useMemo(() => {
    const byKey = new Map(
      (ranks.data?.platforms ?? []).map((platform) => [
        platform.platform,
        platform,
      ]),
    );
    return PLATFORM_ORDER.map(
      (key): HotRankPlatform =>
        byKey.get(key) ?? {
          platform: key,
          display_name: PLATFORM_FALLBACK_NAMES[key],
          status: "unavailable",
          source: null,
          updated_at: null,
          items: [],
        },
    );
  }, [ranks.data]);

  const lastUpdated =
    platforms
      .map((platform) => platform.updated_at)
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) || ranks.data?.generated_at;
  const availableCount = platforms.filter(
    (platform) => platform.status !== "unavailable" && platform.items.length,
  ).length;
  const staleCount = platforms.filter(
    (platform) => platform.status === "stale",
  ).length;

  async function refresh() {
    setRefreshing(true);
    setRefreshError("");
    try {
      const data = await api.hotRanks(true);
      queryClient.setQueryData(["hot-ranks"], data);
    } catch (reason) {
      setRefreshError(
        reason instanceof Error ? reason.message : "刷新失败，请稍后再试。",
      );
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <AppShell>
      <div className="hot-home">
        <section className="hot-hero">
          <div className="hot-hero-copy">
            <span className="eyebrow">
              <Sparkles size={14} aria-hidden="true" /> DAILY SIGNAL
            </span>
            <h1>今天，大家在看什么？</h1>
            <p>小红书、抖音与 B 站的当日热度，一页读完。</p>
          </div>
          <div className="hot-meta">
            <div>
              <CalendarDays size={17} aria-hidden="true" />
              <span>
                <small>今日</small>
                <strong>{formatDate(new Date())}</strong>
              </span>
            </div>
            <div>
              <Clock3 size={17} aria-hidden="true" />
              <span>
                <small>最后更新</small>
                <strong>{formatTime(lastUpdated)}</strong>
              </span>
            </div>
            <button
              type="button"
              className="hot-refresh"
              onClick={refresh}
              disabled={refreshing}
            >
              <RefreshCw
                size={16}
                className={refreshing ? "spin" : ""}
                aria-hidden="true"
              />
              {refreshing ? "更新中…" : "刷新热榜"}
            </button>
          </div>
        </section>

        <div className="hot-summary" role="status" aria-live="polite">
          <span>
            <i className={availableCount ? "online" : "offline"} />
            {ranks.isLoading
              ? "正在连接今日热点…"
              : availableCount === 3 && staleCount === 0
                ? "三大平台榜单已就绪"
                : availableCount
                  ? `${availableCount} 个平台可用${staleCount ? `，其中 ${staleCount} 个为缓存数据` : ""}`
                  : "实时榜单暂不可用"}
          </span>
          <small>每 15 分钟自动更新</small>
        </div>

        {(refreshError || (ranks.isError && !ranks.data)) && (
          <div className="hot-alert" role="alert">
            <CircleAlert size={17} aria-hidden="true" />
            <span>{refreshError || "暂时无法读取热榜，旧数据会继续保留。"}</span>
            <button type="button" onClick={refresh}>
              重试
            </button>
          </div>
        )}

        <div className="platform-tabs" role="tablist" aria-label="选择热榜平台">
          {platforms.map((platform) => (
            <button
              key={platform.platform}
              type="button"
              role="tab"
              aria-selected={activePlatform === platform.platform}
              onClick={() => setActivePlatform(platform.platform)}
            >
              {platform.display_name}
            </button>
          ))}
        </div>

        <section className="rank-grid" aria-label="今日平台热榜">
          {platforms.map((platform) => (
            <div
              key={platform.platform}
              className={
                activePlatform === platform.platform ? "mobile-active" : ""
              }
            >
              <PlatformCard platform={platform} loading={ranks.isLoading} />
            </div>
          ))}
        </section>
      </div>
    </AppShell>
  );
}
