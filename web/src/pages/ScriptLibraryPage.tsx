import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  FilePlus2,
  Inbox,
  LibraryBig,
  LoaderCircle,
  Search,
  X,
} from "lucide-react";
import {
  useEffect,
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

const PAGE_SIZE = 20;
const SCROLL_STORAGE_KEY = "script-library-scroll";

function normalizedOffset(value: string | null) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

export function ScriptLibraryPage() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";
  const offset = normalizedOffset(searchParams.get("offset"));
  const [draftQuery, setDraftQuery] = useState(query);
  const [editorOpen, setEditorOpen] = useState(false);
  const restoredScrollRef = useRef(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const scripts = useQuery({
    queryKey: ["scripts", query, offset],
    queryFn: () => api.scripts(query, PAGE_SIZE, offset),
    placeholderData: (previous) => previous,
  });

  useEffect(() => {
    setDraftQuery(query);
  }, [query]);

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
        window.requestAnimationFrame(() => window.scrollTo(0, parsed.y ?? 0));
      }
    } catch {
      // Ignore stale or malformed browser state and show the page normally.
    }
    window.sessionStorage.removeItem(SCROLL_STORAGE_KEY);
  }, [location.pathname, location.search, scripts.data]);

  useEffect(() => {
    if (
      scripts.data &&
      offset > 0 &&
      scripts.data.items.length === 0 &&
      offset >= scripts.data.total
    ) {
      const next = new URLSearchParams(searchParams);
      next.delete("offset");
      setSearchParams(next, { replace: true });
    }
  }, [offset, scripts.data, searchParams, setSearchParams]);

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

  function goToOffset(nextOffset: number) {
    const next = new URLSearchParams(searchParams);
    if (nextOffset > 0) next.set("offset", String(nextOffset));
    else next.delete("offset");
    setSearchParams(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function rememberListPosition() {
    window.sessionStorage.setItem(
      SCROLL_STORAGE_KEY,
      JSON.stringify({
        url: `${location.pathname}${location.search}`,
        y: window.scrollY,
      }),
    );
  }

  async function createScript(title: string, body: string) {
    await api.createScript(title, body);
    setEditorOpen(false);
    const next = new URLSearchParams(searchParams);
    next.delete("offset");
    setSearchParams(next, { replace: true });
    await queryClient.invalidateQueries({ queryKey: ["scripts"] });
  }

  const result = scripts.data;
  const start = result && result.total > 0 ? result.offset + 1 : 0;
  const end = result ? Math.min(result.offset + result.items.length, result.total) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil((result?.total ?? 0) / PAGE_SIZE));
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
                  ? `“${query}”找到 ${result?.total ?? 0} 篇脚本`
                  : `脚本库共 ${result?.total ?? 0} 篇`}
            </span>
            {scripts.isFetching && !scripts.isPending && (
              <small>
                <LoaderCircle className="spin" size={13} /> 正在更新
              </small>
            )}
          </div>
        </section>

        {scripts.isPending ? (
          <section className="script-library-state" aria-live="polite">
            <LoaderCircle className="spin" size={27} />
            <h2>正在整理脚本…</h2>
            <p>马上就好。</p>
          </section>
        ) : scripts.isError ? (
          <section className="script-library-state error" role="alert">
            <Inbox size={30} />
            <h2>脚本暂时没有加载成功</h2>
            <p>{scripts.error.message}</p>
            <button type="button" onClick={() => void scripts.refetch()}>
              重新加载
            </button>
          </section>
        ) : !result?.items.length ? (
          <section className="script-library-state">
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
          </section>
        ) : (
          <>
            <section
              className="script-library-results"
              aria-label="脚本搜索结果"
            >
              {result.items.map((script) => {
                const detailPath = `/script-library/${encodeURIComponent(script.id)}${
                  currentSearch ? `?${currentSearch}` : ""
                }`;
                return (
                  <Link
                    key={script.id}
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
                        {script.matched_in.includes("title") && query && (
                          <span>标题命中</span>
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
                );
              })}
            </section>

            <nav className="script-library-pagination" aria-label="搜索结果分页">
              <span>
                显示 {start}–{end}，共 {result.total} 篇
              </span>
              <div>
                <button
                  type="button"
                  onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  aria-label="上一页"
                >
                  <ChevronLeft size={17} />
                </button>
                <span>
                  {currentPage} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => goToOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= result.total}
                  aria-label="下一页"
                >
                  <ChevronRight size={17} />
                </button>
              </div>
            </nav>
          </>
        )}
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
