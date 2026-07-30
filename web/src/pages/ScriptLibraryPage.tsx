import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  FilePlus2,
  Inbox,
  LibraryBig,
  LoaderCircle,
  Search,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import {
  HighlightedText,
  ScriptEditorDialog,
  formatScriptDate,
} from "../components/ScriptLibraryShared";
import { api } from "../lib/api";

const PAGE_SIZE = 24;
const SCROLL_STORAGE_KEY = "script-library-scroll";
const DESKTOP_ROW_HEIGHT = 176;
const MOBILE_ROW_HEIGHT = 218;
const VIRTUAL_OVERSCAN = 4;

export function ScriptLibraryPage() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";
  const [draftQuery, setDraftQuery] = useState(query);
  const [editorOpen, setEditorOpen] = useState(false);
  const [listViewport, setListViewport] = useState({
    scrollTop: 0,
    height: 600,
    width: 960,
  });
  const restoredScrollRef = useRef(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const resultsViewportRef = useRef<HTMLElement>(null);
  const scripts = useInfiniteQuery({
    queryKey: ["scripts", query],
    queryFn: ({ pageParam }) => api.scripts(query, PAGE_SIZE, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const nextOffset = lastPage.offset + lastPage.items.length;
      return nextOffset < lastPage.total ? nextOffset : undefined;
    },
  });
  const items = useMemo(
    () => scripts.data?.pages.flatMap((page) => page.items) ?? [],
    [scripts.data],
  );
  const total = scripts.data?.pages[0]?.total ?? 0;
  const rowHeight =
    listViewport.width <= 620 ? MOBILE_ROW_HEIGHT : DESKTOP_ROW_HEIGHT;
  const virtualRowCount =
    items.length +
    (scripts.hasNextPage ||
    scripts.isFetchingNextPage ||
    scripts.isFetchNextPageError
      ? 1
      : 0);
  const virtualStart = Math.max(
    0,
    Math.floor(listViewport.scrollTop / rowHeight) - VIRTUAL_OVERSCAN,
  );
  const virtualEnd = Math.min(
    virtualRowCount,
    Math.ceil(
      (listViewport.scrollTop + listViewport.height) / rowHeight,
    ) + VIRTUAL_OVERSCAN,
  );
  const virtualIndexes = Array.from(
    { length: Math.max(0, virtualEnd - virtualStart) },
    (_, index) => virtualStart + index,
  );

  useEffect(() => {
    setDraftQuery(query);
  }, [query]);

  useEffect(() => {
    const viewport = resultsViewportRef.current;
    if (!viewport) return;

    function measureViewport() {
      const currentViewport = resultsViewportRef.current;
      if (!currentViewport) return;
      setListViewport({
        scrollTop: currentViewport.scrollTop,
        height: currentViewport.clientHeight || 600,
        width: currentViewport.clientWidth || 960,
      });
    }

    measureViewport();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(measureViewport);
    observer?.observe(viewport);
    viewport.addEventListener("scroll", measureViewport, { passive: true });
    window.addEventListener("resize", measureViewport);
    return () => {
      observer?.disconnect();
      viewport.removeEventListener("scroll", measureViewport);
      window.removeEventListener("resize", measureViewport);
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextQuery = draftQuery.trim();
      if (nextQuery === query) return;
      const next = new URLSearchParams();
      if (nextQuery) next.set("q", nextQuery);
      setSearchParams(next, { replace: true });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draftQuery, query, setSearchParams]);

  useEffect(() => {
    restoredScrollRef.current = false;
    if (resultsViewportRef.current) resultsViewportRef.current.scrollTop = 0;
  }, [query]);

  useEffect(() => {
    if (!scripts.data || restoredScrollRef.current) return;
    restoredScrollRef.current = true;
    const stored = window.sessionStorage.getItem(SCROLL_STORAGE_KEY);
    if (!stored) return;
    try {
      const parsed = JSON.parse(stored) as { url?: string; y?: number };
      if (
        parsed.url === `${location.pathname}${location.search}` &&
        typeof parsed.y === "number"
      ) {
        window.requestAnimationFrame(() => {
          if (resultsViewportRef.current) {
            resultsViewportRef.current.scrollTop = parsed.y ?? 0;
          }
        });
      }
    } catch {
      // Ignore stale or malformed browser state and show the page normally.
    }
    window.sessionStorage.removeItem(SCROLL_STORAGE_KEY);
  }, [location.pathname, location.search, scripts.data]);

  useEffect(() => {
    if (
      virtualEnd >= items.length - 2 &&
      scripts.hasNextPage &&
      !scripts.isFetchingNextPage &&
      !scripts.isFetchNextPageError
    ) {
      void scripts.fetchNextPage();
    }
  }, [items.length, scripts, virtualEnd]);

  function searchNow(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams();
    const nextQuery = draftQuery.trim();
    if (nextQuery) next.set("q", nextQuery);
    setSearchParams(next);
  }

  function clearSearch() {
    setDraftQuery("");
    setSearchParams(new URLSearchParams());
    searchInputRef.current?.focus();
  }

  function rememberListPosition() {
    window.sessionStorage.setItem(
      SCROLL_STORAGE_KEY,
      JSON.stringify({
        url: `${location.pathname}${location.search}`,
        y: resultsViewportRef.current?.scrollTop ?? 0,
      }),
    );
  }

  async function createScript(title: string, body: string) {
    await api.createScript(title, body);
    setEditorOpen(false);
    if (resultsViewportRef.current) resultsViewportRef.current.scrollTop = 0;
    await queryClient.invalidateQueries({ queryKey: ["scripts"] });
  }

  const currentSearch = searchParams.toString();

  return (
    <AppShell>
      <div className="script-library-page">
        <section className="script-library-hero">
          <div className="script-library-hero-copy">
            <span className="script-library-hero-icon">
              <LibraryBig size={24} aria-hidden="true" />
            </span>
            <div>
              <span className="eyebrow">SHARED SCRIPT LIBRARY</span>
              <h1>共享脚本库</h1>
              <p>保存团队的好脚本，搜索标题或正文，一键找到并复用。</p>
            </div>
          </div>
          <button
            type="button"
            className="script-library-primary-button"
            onClick={() => setEditorOpen(true)}
          >
            <FilePlus2 size={18} aria-hidden="true" />
            新增脚本
          </button>
        </section>

        <section className="script-library-search-panel" aria-label="搜索脚本">
          <form onSubmit={searchNow}>
            <Search size={19} aria-hidden="true" />
            <input
              ref={searchInputRef}
              type="search"
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="搜索标题或正文关键词"
              aria-label="搜索标题或正文"
              maxLength={200}
            />
            {draftQuery && (
              <button
                type="button"
                className="script-library-clear"
                onClick={clearSearch}
                aria-label="清除搜索"
              >
                <X size={17} />
              </button>
            )}
            <button type="submit" className="script-library-search-button">
              搜索
            </button>
          </form>
          <div className="script-library-result-summary" aria-live="polite">
            <span>
              {scripts.isPending
                ? "正在读取脚本库…"
                : query
                  ? `“${query}”找到 ${total} 篇脚本`
                  : `脚本库共 ${total} 篇`}
            </span>
            {items.length > 0 && (
              <small className="script-library-loaded-count">
                已加载 {items.length} / {total}
              </small>
            )}
            {scripts.isFetching &&
              !scripts.isPending &&
              !scripts.isFetchingNextPage && (
              <small>
                <LoaderCircle className="spin" size={13} /> 正在更新
              </small>
            )}
          </div>
        </section>

        <section
          ref={resultsViewportRef}
          className="script-library-results-viewport"
          aria-label="脚本搜索结果"
        >
          {scripts.isPending ? (
            <div className="script-library-state" aria-live="polite">
              <LoaderCircle className="spin" size={27} />
              <h2>正在整理脚本…</h2>
              <p>马上就好。</p>
            </div>
          ) : scripts.isError && !scripts.data ? (
            <div className="script-library-state error" role="alert">
              <Inbox size={30} />
              <h2>脚本暂时没有加载成功</h2>
              <p>{scripts.error.message}</p>
              <button type="button" onClick={() => void scripts.refetch()}>
                重新加载
              </button>
            </div>
          ) : !items.length ? (
            <div className="script-library-state">
              <Inbox size={30} />
              <h2>{query ? "没有找到匹配的脚本" : "脚本库还是空的"}</h2>
              <p>
                {query
                  ? "试试缩短关键词，或搜索脚本中的其他表达。"
                  : "添加第一篇脚本，让团队随时可以搜索和复用。"}
              </p>
              {query ? (
                <button type="button" onClick={clearSearch}>
                  查看全部脚本
                </button>
              ) : (
                <button type="button" onClick={() => setEditorOpen(true)}>
                  新增脚本
                </button>
              )}
            </div>
          ) : (
            <div
              className="script-library-results-virtual"
              style={{ height: virtualRowCount * rowHeight }}
            >
              {virtualIndexes.map((virtualIndex) => {
                const script = items[virtualIndex];
                if (!script) {
                  return (
                    <div
                      key="load-more"
                      className="script-library-virtual-row"
                      style={{
                        height: rowHeight,
                        transform: `translateY(${virtualIndex * rowHeight}px)`,
                      }}
                    >
                      <div
                        className="script-library-load-more"
                        aria-live="polite"
                      >
                        {scripts.isFetchNextPageError ? (
                          <>
                            <span>后续脚本加载失败</span>
                            <button
                              type="button"
                              onClick={() => void scripts.fetchNextPage()}
                            >
                              重新加载
                            </button>
                          </>
                        ) : (
                          <>
                            <LoaderCircle className="spin" size={17} />
                            正在加载更多脚本…
                          </>
                        )}
                      </div>
                    </div>
                  );
                }
                const detailPath = `/script-library/${encodeURIComponent(script.id)}${
                  currentSearch ? `?${currentSearch}` : ""
                }`;
                const titleMatched = script.matched_in.includes("title");
                const bodyMatched = script.matched_in.includes("body");
                const matchLabel =
                  titleMatched && bodyMatched
                    ? "标题和正文命中"
                    : titleMatched
                      ? "标题命中"
                      : bodyMatched
                        ? "正文命中"
                        : "";
                return (
                  <div
                    key={script.id}
                    className="script-library-virtual-row"
                    style={{
                      height: rowHeight,
                      transform: `translateY(${virtualIndex * rowHeight}px)`,
                    }}
                  >
                    <Link
                      to={detailPath}
                      state={{
                        from: `${location.pathname}${location.search}`,
                      }}
                      className="script-library-card"
                      onClick={rememberListPosition}
                    >
                      <div className="script-library-card-main">
                        <div className="script-library-card-title">
                          <h2 aria-label={script.title}>
                            <HighlightedText text={script.title} query={query} />
                          </h2>
                          {query && matchLabel && (
                            <span
                              className={`script-library-match-tag ${
                                titleMatched && bodyMatched
                                  ? "both"
                                  : bodyMatched
                                    ? "body"
                                    : "title"
                              }`}
                            >
                              {matchLabel}
                            </span>
                          )}
                        </div>
                        <p>
                          <HighlightedText text={script.excerpt} query={query} />
                        </p>
                      </div>
                      <footer className="script-library-card-footer">
                        <div>
                          <span>{script.character_count.toLocaleString()} 字</span>
                          <span>最后修改：{script.updated_by.username}</span>
                          <time dateTime={script.updated_at}>
                            {formatScriptDate(script.updated_at)}
                          </time>
                        </div>
                        <strong>
                          查看详情 <ArrowRight size={15} aria-hidden="true" />
                        </strong>
                      </footer>
                    </Link>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {editorOpen && (
        <ScriptEditorDialog
          onClose={() => setEditorOpen(false)}
          onSave={createScript}
        />
      )}
    </AppShell>
  );
}
