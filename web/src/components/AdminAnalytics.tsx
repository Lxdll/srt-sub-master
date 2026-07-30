import {
  BarChart,
  LineChart,
} from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption } from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Globe2,
  Link2,
  MapPin,
  MousePointerClick,
  Search,
  UserRound,
  Users,
} from "lucide-react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { api } from "../lib/api";
import { useTheme } from "../lib/theme";
import type { AnalyticsDays } from "../types";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
]);

export type AnalyticsTab = "visits" | "ip-links" | "actions";

const ACTION_LABELS: Record<string, string> = {
  "auth.login": "账号登录",
  "auth.logout": "退出登录",
  "auth.password_change": "修改密码",
  "admin.user.create": "创建账号",
  "admin.user.permissions_update": "修改权限",
  "admin.user.password_reset": "重置密码",
  "device.pair_code.create": "创建设备配对码",
  "device.pair.complete": "完成设备配对",
  "subtitle.task.create": "创建字幕任务",
  "subtitle.srt.import": "导入 SRT",
  "subtitle.segment.edit": "编辑字幕",
  "subtitle.task.retry": "重试字幕任务",
  "subtitle.task.relink": "重新关联设备",
  "subtitle.task.export": "导出字幕",
  "subtitle.task.delete": "删除字幕任务",
  "douyin.parse": "解析抖音视频",
  "douyin.download": "下载抖音视频",
  "douyin.transcription.create": "创建抖音转写",
  "prohibited_words.check": "违禁词检测",
  "prohibited_words.custom.add": "添加个人违禁词",
  "prohibited_words.custom.delete": "删除个人违禁词",
  "script_analysis.run": "脚本分析",
  "script_library.create": "创建脚本",
  "script_library.update": "修改脚本",
  "script_library.delete": "删除脚本",
  "hot_ranks.refresh": "刷新热榜",
};

const PATH_LABELS: Record<string, string> = {
  "/": "首页",
  "/login": "登录页",
  "/tools": "工具中心",
  "/subtitle": "字幕工作台",
  "/douyin": "抖音下载",
  "/douyin-transcribe": "抖音转写",
  "/prohibited-words": "违禁词检测",
  "/script-analysis": "脚本分析",
  "/script-library": "脚本库",
};

function actionLabel(key: string) {
  return ACTION_LABELS[key] ?? key;
}

function pathLabel(path: string) {
  if (PATH_LABELS[path]) return PATH_LABELS[path];
  if (path.startsWith("/tasks/")) return "字幕编辑";
  if (path.startsWith("/script-library/")) return "脚本详情";
  return path;
}

function formatDateTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDay(value: string) {
  const [, month, day] = value.split("-");
  return `${month}-${day}`;
}

function Chart({
  option,
  label,
}: {
  option: EChartsCoreOption;
  label: string;
}) {
  const elementRef = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;
    const chart = echarts.init(element, theme, { renderer: "svg" });
    chart.setOption(option);
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => chart.resize());
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      chart.dispose();
    };
  }, [option, theme]);

  return <div className="analytics-chart" ref={elementRef} role="img" aria-label={label} />;
}

function DaysSelector({
  value,
  onChange,
}: {
  value: AnalyticsDays;
  onChange: (days: AnalyticsDays) => void;
}) {
  return (
    <div className="analytics-days" aria-label="统计时间范围">
      {([7, 30, 90] as const).map((days) => (
        <button
          type="button"
          key={days}
          className={value === days ? "active" : ""}
          onClick={() => onChange(days)}
        >
          {days} 天
        </button>
      ))}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone = "teal",
}: {
  icon: ReactNode;
  label: string;
  value: number;
  tone?: "teal" | "orange" | "green" | "red";
}) {
  return (
    <article className={`analytics-stat-card ${tone}`}>
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value.toLocaleString("zh-CN")}</strong>
      </div>
    </article>
  );
}

function LoadingPanel({ text }: { text: string }) {
  return <div className="analytics-state">{text}</div>;
}

function LoadMore({
  hasMore,
  busy,
  onClick,
}: {
  hasMore: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  if (!hasMore) return null;
  return (
    <button
      className="analytics-load-more"
      type="button"
      disabled={busy}
      onClick={onClick}
    >
      {busy ? "正在读取…" : "加载更多"}
    </button>
  );
}

function VisitsAnalytics() {
  const [days, setDays] = useState<AnalyticsDays>(30);
  const overview = useQuery({
    queryKey: ["admin-analytics-overview", days],
    queryFn: () => api.analyticsOverview(days),
    refetchInterval: 60_000,
  });
  const visits = useInfiniteQuery({
    queryKey: ["admin-analytics-visits", days],
    queryFn: ({ pageParam }) => api.analyticsVisits(days, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 60_000,
  });
  const visitItems = visits.data?.pages.flatMap((page) => page.items) ?? [];

  const trendOption = useMemo<EChartsCoreOption>(() => {
    const data = overview.data?.daily ?? [];
    return {
      color: ["#62c9ba", "#e76b45"],
      tooltip: { trigger: "axis" },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: "#a7a99f", fontSize: 10 },
      },
      grid: { top: 42, left: 46, right: 20, bottom: 30 },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data.map((item) => formatDay(item.day)),
        axisLabel: { color: "#85877d", fontSize: 9 },
        axisLine: { lineStyle: { color: "rgba(140,140,130,.25)" } },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: "#85877d", fontSize: 9 },
        splitLine: { lineStyle: { color: "rgba(140,140,130,.12)" } },
      },
      series: [
        {
          name: "访问量",
          type: "line",
          smooth: true,
          symbol: "none",
          areaStyle: { opacity: 0.08 },
          data: data.map((item) => item.page_views),
        },
        {
          name: "独立 IP",
          type: "line",
          smooth: true,
          symbol: "none",
          data: data.map((item) => item.unique_ips),
        },
      ],
    };
  }, [overview.data]);

  const locationOption = useMemo<EChartsCoreOption>(() => {
    const data = [...(overview.data?.locations ?? [])].reverse();
    return {
      color: ["#e76b45"],
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { top: 8, left: 92, right: 24, bottom: 24 },
      xAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: "#85877d", fontSize: 9 },
        splitLine: { lineStyle: { color: "rgba(140,140,130,.12)" } },
      },
      yAxis: {
        type: "category",
        data: data.map((item) => item.label),
        axisLabel: {
          color: "#a7a99f",
          fontSize: 9,
          width: 80,
          overflow: "truncate",
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "访问量",
          type: "bar",
          barMaxWidth: 16,
          data: data.map((item) => item.page_views),
          itemStyle: { borderRadius: [0, 5, 5, 0] },
        },
      ],
    };
  }, [overview.data]);

  return (
    <>
      <div className="analytics-toolbar">
        <div>
          <span className="eyebrow">TRAFFIC OVERVIEW</span>
          <h1>访问统计</h1>
          <p>查看主站页面访问、独立 IP 和地区分布。</p>
        </div>
        <DaysSelector value={days} onChange={setDays} />
      </div>
      {overview.isLoading ? (
        <LoadingPanel text="正在读取访问统计…" />
      ) : overview.isError || !overview.data ? (
        <LoadingPanel text="访问统计读取失败，请稍后重试。" />
      ) : (
        <>
          <div className="analytics-stat-grid">
            <StatCard
              icon={<MousePointerClick size={20} />}
              label="今日访问"
              value={overview.data.summary.today_page_views}
            />
            <StatCard
              icon={<Globe2 size={20} />}
              label="今日独立 IP"
              value={overview.data.summary.today_unique_ips}
              tone="orange"
            />
            <StatCard
              icon={<Activity size={20} />}
              label={`${days} 天访问`}
              value={overview.data.summary.period_page_views}
              tone="green"
            />
            <StatCard
              icon={<Users size={20} />}
              label={`${days} 天独立 IP`}
              value={overview.data.summary.period_unique_ips}
              tone="orange"
            />
          </div>
          {(!overview.data.geo_status.ipv4 ||
            !overview.data.geo_status.ipv6) && (
            <div className="analytics-warning">
              <AlertTriangle size={16} />
              部分 IP 归属地库未加载，访问仍会正常记录并显示为“未知”。
            </div>
          )}
          <div className="analytics-chart-grid">
            <section className="analytics-panel">
              <header>
                <div>
                  <h2>访问趋势</h2>
                  <p>按上海时区统计每日访问与独立 IP</p>
                </div>
              </header>
              <Chart option={trendOption} label="每日访问趋势图" />
            </section>
            <section className="analytics-panel">
              <header>
                <div>
                  <h2>访问地区</h2>
                  <p>近似城市级归属地前十名</p>
                </div>
              </header>
              <Chart option={locationOption} label="访问地区排行图" />
            </section>
          </div>
        </>
      )}
      <section className="analytics-panel analytics-table-panel">
        <header>
          <div>
            <h2>最近访问</h2>
            <p>完整 IP 明细将在 90 天后自动删除</p>
          </div>
          <Clock3 size={18} />
        </header>
        {visits.isLoading ? (
          <LoadingPanel text="正在读取最近访问…" />
        ) : visits.isError ? (
          <LoadingPanel text="最近访问读取失败。" />
        ) : visitItems.length === 0 ? (
          <LoadingPanel text="当前时间范围内还没有访问记录。" />
        ) : (
          <>
            <div className="analytics-table-wrap">
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>IP</th>
                    <th>归属地</th>
                    <th>页面</th>
                    <th>账号</th>
                  </tr>
                </thead>
                <tbody>
                  {visitItems.map((item) => (
                    <tr key={item.id}>
                      <td>{formatDateTime(item.occurred_at)}</td>
                      <td><code>{item.ip_address}</code></td>
                      <td>{item.location.label}</td>
                      <td>{pathLabel(item.path)}</td>
                      <td>{item.username ?? "未登录"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <LoadMore
              hasMore={Boolean(visits.hasNextPage)}
              busy={visits.isFetchingNextPage}
              onClick={() => void visits.fetchNextPage()}
            />
          </>
        )}
      </section>
    </>
  );
}

function IpLinksAnalytics() {
  const [days, setDays] = useState<AnalyticsDays>(30);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const links = useInfiniteQuery({
    queryKey: ["admin-analytics-ip-links", days, query],
    queryFn: ({ pageParam }) =>
      api.analyticsIpUsers(days, query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 60_000,
  });
  const items = links.data?.pages.flatMap((page) => page.items) ?? [];

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQuery(searchInput.trim());
  }

  return (
    <>
      <div className="analytics-toolbar">
        <div>
          <span className="eyebrow">IP &amp; ACCOUNT RELATIONSHIPS</span>
          <h1>IP 关联</h1>
          <p>成功登录后建立关联；匿名访问不会追溯到账号。</p>
        </div>
        <DaysSelector value={days} onChange={setDays} />
      </div>
      <section className="analytics-panel analytics-table-panel">
        <header className="analytics-filter-header">
          <div>
            <h2>IP 与账号</h2>
            <p>同一 IP 可以关联多个账号，同一账号也可以使用多个 IP</p>
          </div>
          <form className="analytics-search" onSubmit={submitSearch}>
            <Search size={15} />
            <input
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="搜索 IP 或用户名"
              maxLength={100}
            />
            <button type="submit">搜索</button>
          </form>
        </header>
        {links.isLoading ? (
          <LoadingPanel text="正在读取 IP 关联…" />
        ) : links.isError ? (
          <LoadingPanel text="IP 关联读取失败。" />
        ) : items.length === 0 ? (
          <LoadingPanel text={query ? "没有匹配的 IP 或账号。" : "还没有登录关联记录。"} />
        ) : (
          <>
            <div className="ip-link-list">
              {items.map((item) => (
                <article className="ip-link-card" key={item.ip_address}>
                  <div className="ip-link-primary">
                    <span><Link2 size={18} /></span>
                    <div>
                      <code>{item.ip_address}</code>
                      <small><MapPin size={12} /> {item.location.label}</small>
                    </div>
                    <time>最近 {formatDateTime(item.last_seen_at)}</time>
                  </div>
                  <div className="ip-link-metrics">
                    <span>登录 <strong>{item.login_count}</strong></span>
                    <span>访问 <strong>{item.page_view_count}</strong></span>
                    <span>操作 <strong>{item.action_count}</strong></span>
                    <span>首次 <strong>{formatDateTime(item.first_seen_at)}</strong></span>
                  </div>
                  <div className="ip-link-users">
                    {item.users.map((account) => (
                      <div key={account.id}>
                        <span><UserRound size={14} /> {account.username}</span>
                        <small>
                          登录 {account.login_count} · 访问 {account.page_view_count} ·
                          操作 {account.action_count}
                        </small>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <LoadMore
              hasMore={Boolean(links.hasNextPage)}
              busy={links.isFetchingNextPage}
              onClick={() => void links.fetchNextPage()}
            />
          </>
        )}
      </section>
    </>
  );
}

function ActionsAnalytics() {
  const [days, setDays] = useState<AnalyticsDays>(30);
  const [userId, setUserId] = useState("");
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState<"" | "success" | "failure">("");
  const overview = useQuery({
    queryKey: ["admin-actions-overview", days],
    queryFn: () => api.analyticsActionsOverview(days),
    refetchInterval: 60_000,
  });
  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: api.adminUsers,
  });
  const actions = useInfiniteQuery({
    queryKey: ["admin-actions", days, userId, action, outcome],
    queryFn: ({ pageParam }) =>
      api.analyticsActions(days, {
        user_id: userId || undefined,
        action: action || undefined,
        outcome: outcome || undefined,
        cursor: pageParam,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 60_000,
  });
  const actionItems = actions.data?.pages.flatMap((page) => page.items) ?? [];

  const trendOption = useMemo<EChartsCoreOption>(() => {
    const data = overview.data?.daily ?? [];
    return {
      color: ["#62c9ba", "#e76b45"],
      tooltip: { trigger: "axis" },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: "#a7a99f", fontSize: 10 },
      },
      grid: { top: 42, left: 46, right: 20, bottom: 30 },
      xAxis: {
        type: "category",
        data: data.map((item) => formatDay(item.day)),
        axisLabel: { color: "#85877d", fontSize: 9 },
        axisLine: { lineStyle: { color: "rgba(140,140,130,.25)" } },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: "#85877d", fontSize: 9 },
        splitLine: { lineStyle: { color: "rgba(140,140,130,.12)" } },
      },
      series: [
        {
          name: "成功",
          type: "line",
          stack: "events",
          areaStyle: { opacity: 0.12 },
          symbol: "none",
          data: data.map((item) => item.success),
        },
        {
          name: "失败",
          type: "line",
          stack: "events",
          areaStyle: { opacity: 0.12 },
          symbol: "none",
          data: data.map((item) => item.failure),
        },
      ],
    };
  }, [overview.data]);

  const rankingOption = useMemo<EChartsCoreOption>(() => {
    const data = [...(overview.data?.top_actions ?? [])].reverse();
    return {
      color: ["#62c9ba"],
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { top: 8, left: 116, right: 24, bottom: 24 },
      xAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: "#85877d", fontSize: 9 },
        splitLine: { lineStyle: { color: "rgba(140,140,130,.12)" } },
      },
      yAxis: {
        type: "category",
        data: data.map((item) => actionLabel(item.action_key)),
        axisLabel: {
          color: "#a7a99f",
          fontSize: 9,
          width: 108,
          overflow: "truncate",
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [
        {
          name: "操作次数",
          type: "bar",
          barMaxWidth: 16,
          data: data.map((item) => item.event_count),
          itemStyle: { borderRadius: [0, 5, 5, 0] },
        },
      ],
    };
  }, [overview.data]);

  return (
    <>
      <div className="analytics-toolbar">
        <div>
          <span className="eyebrow">SERVER-SIDE EVENT TRACKING</span>
          <h1>操作记录</h1>
          <p>记录可信的业务结果和安全事件，不保存正文、密码或令牌。</p>
        </div>
        <DaysSelector value={days} onChange={setDays} />
      </div>
      {overview.data && (
        <>
          <div className="analytics-stat-grid">
            <StatCard
              icon={<Activity size={20} />}
              label={`${days} 天操作`}
              value={overview.data.summary.total}
            />
            <StatCard
              icon={<CheckCircle2 size={20} />}
              label="成功"
              value={overview.data.summary.success}
              tone="green"
            />
            <StatCard
              icon={<AlertTriangle size={20} />}
              label="失败"
              value={overview.data.summary.failure}
              tone="red"
            />
            <StatCard
              icon={<Users size={20} />}
              label="活跃用户"
              value={overview.data.summary.active_users}
              tone="orange"
            />
          </div>
          <div className="analytics-chart-grid">
            <section className="analytics-panel">
              <header><div><h2>操作趋势</h2><p>成功与失败事件</p></div></header>
              <Chart option={trendOption} label="每日操作趋势图" />
            </section>
            <section className="analytics-panel">
              <header><div><h2>热门操作</h2><p>关键业务事件前十名</p></div></header>
              <Chart option={rankingOption} label="热门操作排行图" />
            </section>
          </div>
        </>
      )}
      <section className="analytics-panel analytics-table-panel">
        <header className="analytics-filter-header">
          <div><h2>操作明细</h2><p>明细保留 90 天，长期仅保留聚合数量</p></div>
          <div className="analytics-filters">
            <select value={userId} onChange={(event) => setUserId(event.target.value)}>
              <option value="">全部用户</option>
              {users.data?.map((item) => (
                <option value={item.id} key={item.id}>{item.username}</option>
              ))}
            </select>
            <select value={action} onChange={(event) => setAction(event.target.value)}>
              <option value="">全部操作</option>
              {Object.entries(ACTION_LABELS).map(([key, label]) => (
                <option value={key} key={key}>{label}</option>
              ))}
            </select>
            <select
              value={outcome}
              onChange={(event) =>
                setOutcome(event.target.value as "" | "success" | "failure")
              }
            >
              <option value="">全部结果</option>
              <option value="success">成功</option>
              <option value="failure">失败</option>
            </select>
          </div>
        </header>
        {actions.isLoading ? (
          <LoadingPanel text="正在读取操作记录…" />
        ) : actions.isError ? (
          <LoadingPanel text="操作记录读取失败。" />
        ) : actionItems.length === 0 ? (
          <LoadingPanel text="当前筛选条件下没有操作记录。" />
        ) : (
          <>
            <div className="analytics-table-wrap">
              <table className="analytics-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>用户</th>
                    <th>操作</th>
                    <th>结果</th>
                    <th>IP / 归属地</th>
                    <th>资源</th>
                  </tr>
                </thead>
                <tbody>
                  {actionItems.map((item) => (
                    <tr key={item.id}>
                      <td>{formatDateTime(item.occurred_at)}</td>
                      <td>{item.username ?? "匿名/未知"}</td>
                      <td>{actionLabel(item.action_key)}</td>
                      <td>
                        <span className={`event-outcome ${item.outcome}`}>
                          {item.outcome === "success" ? "成功" : `失败 ${item.http_status}`}
                        </span>
                      </td>
                      <td>
                        <code>{item.ip_address}</code>
                        <small className="table-subline">{item.location.label}</small>
                      </td>
                      <td>
                        {item.resource_type && item.resource_id
                          ? `${item.resource_type} · ${item.resource_id.slice(0, 8)}`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <LoadMore
              hasMore={Boolean(actions.hasNextPage)}
              busy={actions.isFetchingNextPage}
              onClick={() => void actions.fetchNextPage()}
            />
          </>
        )}
      </section>
    </>
  );
}

export function AdminAnalytics({ tab }: { tab: AnalyticsTab }) {
  if (tab === "ip-links") return <IpLinksAnalytics />;
  if (tab === "actions") return <ActionsAnalytics />;
  return <VisitsAnalytics />;
}
