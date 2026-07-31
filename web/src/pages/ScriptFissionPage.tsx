import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  Copy,
  FileText,
  LibraryBig,
  LoaderCircle,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Square,
  WandSparkles,
  X,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { hasPermission } from "../lib/permissions";
import type {
  ScriptFissionDirection,
  ScriptFissionPlan,
  ScriptFissionSourcePayload,
  ScriptLibraryDetail,
} from "../types";

const MAX_SOURCE_LENGTH = 30_000;
const MAX_REQUIREMENTS_LENGTH = 1_000;
const PICKER_PAGE_SIZE = 10;

type VariantState = {
  status: "loading" | "success" | "error";
  title: string;
  body: string;
  error: string;
  saving: boolean;
  copied: boolean;
  saved: { id: string; title: string; body: string } | null;
};

function emptyVariant(): VariantState {
  return {
    status: "loading",
    title: "",
    body: "",
    error: "",
    saving: false,
    copied: false,
    saved: null,
  };
}

function LibraryPicker({
  onClose,
  onSelect,
}: {
  onClose: () => void;
  onSelect: (script: ScriptLibraryDetail) => void;
}) {
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectingId, setSelectingId] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const dialogRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const scripts = useQuery({
    queryKey: ["script-fission-picker", query, offset],
    queryFn: () => api.scripts(query, PICKER_PAGE_SIZE, offset),
  });

  useEffect(() => {
    searchRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !selectingId) onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, selectingId]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setOffset(0);
    setQuery(draftQuery.trim());
  }

  async function select(scriptId: string) {
    setSelectingId(scriptId);
    setSelectionError("");
    try {
      onSelect(await api.script(scriptId));
    } catch (reason) {
      setSelectionError(
        reason instanceof Error ? reason.message : "脚本读取失败，请稍后重试。",
      );
    } finally {
      setSelectingId("");
    }
  }

  const page = scripts.data;
  const pageNumber = Math.floor(offset / PICKER_PAGE_SIZE) + 1;
  const pageCount = page
    ? Math.max(1, Math.ceil(page.total / PICKER_PAGE_SIZE))
    : 1;

  return (
    <div
      className="fission-picker-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !selectingId) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="fission-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fission-picker-title"
      >
        <header>
          <div>
            <LibraryBig size={21} aria-hidden="true" />
            <div>
              <small>SHARED SCRIPT LIBRARY</small>
              <h2 id="fission-picker-title">选择来源脚本</h2>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={Boolean(selectingId)}
            aria-label="关闭脚本选择器"
          >
            <X size={19} />
          </button>
        </header>

        <form className="fission-picker-search" onSubmit={submitSearch}>
          <Search size={18} aria-hidden="true" />
          <input
            ref={searchRef}
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="搜索标题或正文关键词"
            aria-label="搜索共享脚本"
            maxLength={200}
          />
          <button type="submit">搜索</button>
        </form>

        <div className="fission-picker-results" aria-live="polite">
          {scripts.isPending ? (
            <div className="fission-picker-state">
              <LoaderCircle className="spin" size={24} />
              正在读取脚本库…
            </div>
          ) : scripts.isError ? (
            <div className="fission-picker-state error" role="alert">
              <AlertCircle size={23} />
              <span>{scripts.error.message}</span>
              <button type="button" onClick={() => void scripts.refetch()}>
                重试
              </button>
            </div>
          ) : !page?.items.length ? (
            <div className="fission-picker-state">
              <FileText size={24} />
              {query ? "没有找到匹配的脚本" : "共享脚本库还是空的"}
            </div>
          ) : (
            page.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="fission-picker-item"
                onClick={() => void select(item.id)}
                disabled={Boolean(selectingId)}
              >
                <div>
                  <strong>{item.title}</strong>
                  <small>{item.character_count.toLocaleString()} 字</small>
                </div>
                <p>{item.excerpt}</p>
                <span>
                  {selectingId === item.id ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <ArrowRight size={16} />
                  )}
                  选择
                </span>
              </button>
            ))
          )}
        </div>

        {selectionError && (
          <p className="fission-inline-error" role="alert">
            {selectionError}
          </p>
        )}

        <footer>
          <span>
            第 {pageNumber} / {pageCount} 页
            {page ? ` · 共 ${page.total} 篇` : ""}
          </span>
          <div>
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - PICKER_PAGE_SIZE))}
              disabled={offset === 0 || scripts.isFetching}
            >
              <ArrowLeft size={15} /> 上一页
            </button>
            <button
              type="button"
              onClick={() => setOffset(offset + PICKER_PAGE_SIZE)}
              disabled={
                !page ||
                offset + page.items.length >= page.total ||
                scripts.isFetching
              }
            >
              下一页 <ArrowRight size={15} />
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

export function ScriptFissionPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const canUseLibrary = hasPermission(user, "script_library");
  const [sourceMode, setSourceMode] = useState<"text" | "library">("text");
  const [text, setText] = useState("");
  const [selectedScript, setSelectedScript] =
    useState<ScriptLibraryDetail | null>(null);
  const [requirements, setRequirements] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [plan, setPlan] = useState<ScriptFissionPlan | null>(null);
  const [variants, setVariants] = useState<Record<string, VariantState>>({});
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState("");
  const [preselecting, setPreselecting] = useState(false);
  const abortControllers = useRef(new Set<AbortController>());
  const preselectedRef = useRef("");

  const sourceLength =
    sourceMode === "library"
      ? (selectedScript?.character_count ?? 0)
      : text.length;
  const hasActiveRequests = planning || Object.values(variants).some(
    (item) => item.status === "loading",
  );

  const sourcePayload = useMemo<ScriptFissionSourcePayload>(
    () => ({
      ...(sourceMode === "library" && selectedScript
        ? { source_script_id: selectedScript.id }
        : { text }),
      ...(requirements.trim() ? { requirements: requirements.trim() } : {}),
    }),
    [requirements, selectedScript, sourceMode, text],
  );

  useEffect(() => {
    const scriptId = searchParams.get("scriptId") ?? "";
    if (
      !scriptId ||
      !canUseLibrary ||
      preselectedRef.current === scriptId
    ) {
      return;
    }
    preselectedRef.current = scriptId;
    setPreselecting(true);
    setError("");
    void api
      .script(scriptId)
      .then((script) => {
        setSelectedScript(script);
        setSourceMode("library");
      })
      .catch((reason) => {
        setError(
          reason instanceof Error
            ? reason.message
            : "预选的共享脚本读取失败。",
        );
      })
      .finally(() => setPreselecting(false));
  }, [canUseLibrary, searchParams]);

  useEffect(
    () => () => {
      for (const controller of abortControllers.current) controller.abort();
    },
    [],
  );

  function cancelRequests() {
    for (const controller of abortControllers.current) controller.abort();
    abortControllers.current.clear();
    setPlanning(false);
    setVariants((current) =>
      Object.fromEntries(
        Object.entries(current).map(([id, item]) => [
          id,
          item.status === "loading"
            ? { ...item, status: "error", error: "生成已取消，可单独重试。" }
            : item,
        ]),
      ),
    );
  }

  function invalidateResults() {
    cancelRequests();
    setPlan(null);
    setVariants({});
    setError("");
  }

  function chooseMode(mode: "text" | "library") {
    if (mode === "library" && !canUseLibrary) return;
    if (mode === sourceMode) return;
    invalidateResults();
    setSourceMode(mode);
    if (mode === "text") {
      const next = new URLSearchParams(searchParams);
      next.delete("scriptId");
      setSearchParams(next, { replace: true });
    }
  }

  function chooseScript(script: ScriptLibraryDetail) {
    invalidateResults();
    setSelectedScript(script);
    setSourceMode("library");
    setPickerOpen(false);
    const next = new URLSearchParams(searchParams);
    next.set("scriptId", script.id);
    setSearchParams(next, { replace: true });
  }

  async function generateDirection(
    direction: ScriptFissionDirection,
    currentPlan: ScriptFissionPlan,
    payload: ScriptFissionSourcePayload,
  ) {
    const controller = new AbortController();
    abortControllers.current.add(controller);
    setVariants((current) => ({
      ...current,
      [direction.id]: {
        ...(current[direction.id] ?? emptyVariant()),
        status: "loading",
        error: "",
      },
    }));
    try {
      const generated = await api.generateScriptFission(
        {
          ...payload,
          directions: currentPlan.directions,
          direction_id: direction.id,
        },
        controller.signal,
      );
      setVariants((current) => ({
        ...current,
        [direction.id]: {
          ...emptyVariant(),
          status: "success",
          title: generated.title,
          body: generated.body,
        },
      }));
    } catch (reason) {
      const aborted =
        reason instanceof DOMException && reason.name === "AbortError";
      setVariants((current) => ({
        ...current,
        [direction.id]: {
          ...(current[direction.id] ?? emptyVariant()),
          status: "error",
          error: aborted
            ? "生成已取消，可单独重试。"
            : reason instanceof Error
              ? reason.message
              : "这个版本生成失败，请重试。",
        },
      }));
    } finally {
      abortControllers.current.delete(controller);
    }
  }

  async function startFission() {
    if (sourceMode === "text" && !text.trim()) {
      setError("请先粘贴来源脚本。");
      return;
    }
    if (sourceMode === "library" && !selectedScript) {
      setError("请先从共享脚本库选择一篇来源脚本。");
      return;
    }

    cancelRequests();
    setPlan(null);
    setVariants({});
    setError("");
    setPlanning(true);
    const payload = sourcePayload;
    const controller = new AbortController();
    abortControllers.current.add(controller);
    try {
      const createdPlan = await api.planScriptFission(
        payload,
        controller.signal,
      );
      setPlan(createdPlan);
      setVariants(
        Object.fromEntries(
          createdPlan.directions.map((direction) => [
            direction.id,
            emptyVariant(),
          ]),
        ),
      );
      setPlanning(false);
      await Promise.allSettled(
        createdPlan.directions.map((direction) =>
          generateDirection(direction, createdPlan, payload),
        ),
      );
    } catch (reason) {
      const aborted =
        reason instanceof DOMException && reason.name === "AbortError";
      setError(
        aborted
          ? "本次裂变已取消。"
          : reason instanceof Error
            ? reason.message
            : "裂变规划失败，请稍后重试。",
      );
      setPlanning(false);
    } finally {
      abortControllers.current.delete(controller);
    }
  }

  function updateVariant(
    directionId: string,
    field: "title" | "body",
    value: string,
  ) {
    setVariants((current) => ({
      ...current,
      [directionId]: {
        ...current[directionId],
        [field]: value,
        error: "",
      },
    }));
  }

  async function copyVariant(directionId: string) {
    const item = variants[directionId];
    if (!item) return;
    try {
      await navigator.clipboard.writeText(
        `${item.title.trim()}\n\n${item.body}`.trim(),
      );
      setVariants((current) => ({
        ...current,
        [directionId]: { ...current[directionId], copied: true },
      }));
      window.setTimeout(
        () =>
          setVariants((current) =>
            current[directionId]
              ? {
                  ...current,
                  [directionId]: {
                    ...current[directionId],
                    copied: false,
                  },
                }
              : current,
          ),
        1_800,
      );
    } catch {
      setVariants((current) => ({
        ...current,
        [directionId]: {
          ...current[directionId],
          error: "复制失败，请检查浏览器剪贴板权限。",
        },
      }));
    }
  }

  async function saveVariant(directionId: string) {
    const item = variants[directionId];
    const title = item?.title.trim() ?? "";
    const body = item?.body.trim() ?? "";
    if (!title || !body) {
      setVariants((current) => ({
        ...current,
        [directionId]: {
          ...current[directionId],
          error: "标题和正文不能为空。",
        },
      }));
      return;
    }
    setVariants((current) => ({
      ...current,
      [directionId]: {
        ...current[directionId],
        saving: true,
        error: "",
      },
    }));
    try {
      const saved = await api.createScript(title, item.body);
      setVariants((current) => ({
        ...current,
        [directionId]: {
          ...current[directionId],
          saving: false,
          saved: { id: saved.id, title, body: item.body },
        },
      }));
    } catch (reason) {
      setVariants((current) => ({
        ...current,
        [directionId]: {
          ...current[directionId],
          saving: false,
          error:
            reason instanceof Error ? reason.message : "保存失败，请稍后重试。",
        },
      }));
    }
  }

  return (
    <AppShell>
      <main className="fission-page">
        <header className="fission-hero">
          <div>
            <span className="fission-hero-icon">
              <WandSparkles size={25} aria-hidden="true" />
            </span>
            <div>
              <span className="eyebrow">SCRIPT FISSION</span>
              <h1>脚本裂变</h1>
              <p>从一个好脚本出发，规划三个方向，再创作三篇完整新脚本。</p>
            </div>
          </div>
          <aside>
            <Sparkles size={18} aria-hidden="true" />
            先规划、再并行创作；内容只在本次页面中临时保留。
          </aside>
        </header>

        <div className="fission-workspace">
          <section className="fission-source-panel" aria-label="裂变设置">
            <div className="fission-panel-heading">
              <span>01</span>
              <div>
                <h2>选择来源</h2>
                <p>粘贴脚本，或从团队共享库直接选择。</p>
              </div>
            </div>

            <div className="fission-source-tabs">
              <button
                type="button"
                className={sourceMode === "text" ? "active" : ""}
                onClick={() => chooseMode("text")}
              >
                <FileText size={16} /> 粘贴输入
              </button>
              <button
                type="button"
                className={sourceMode === "library" ? "active" : ""}
                onClick={() => chooseMode("library")}
                disabled={!canUseLibrary}
                title={
                  canUseLibrary ? undefined : "当前账号没有共享脚本库权限"
                }
              >
                <LibraryBig size={16} /> 共享脚本库
              </button>
            </div>

            {sourceMode === "text" ? (
              <label className="fission-source-input">
                <span>来源脚本</span>
                <textarea
                  value={text}
                  onChange={(event) => {
                    invalidateResults();
                    setText(event.target.value);
                  }}
                  maxLength={MAX_SOURCE_LENGTH}
                  placeholder="在这里粘贴需要进行再创作的完整脚本…"
                  aria-label="来源脚本"
                />
                <small>
                  {text.length.toLocaleString()} /{" "}
                  {MAX_SOURCE_LENGTH.toLocaleString()} 字
                </small>
              </label>
            ) : (
              <div className="fission-library-source">
                {preselecting ? (
                  <div className="fission-library-empty">
                    <LoaderCircle className="spin" size={22} />
                    正在打开共享脚本…
                  </div>
                ) : selectedScript ? (
                  <article>
                    <div>
                      <LibraryBig size={18} />
                      <span>已选择共享脚本</span>
                    </div>
                    <h3>{selectedScript.title}</h3>
                    <p>{selectedScript.body}</p>
                    <footer>
                      <small>
                        {selectedScript.character_count.toLocaleString()} 字
                      </small>
                      <button
                        type="button"
                        onClick={() => setPickerOpen(true)}
                      >
                        更换脚本
                      </button>
                    </footer>
                  </article>
                ) : (
                  <div className="fission-library-empty">
                    <LibraryBig size={25} />
                    <strong>还没有选择来源脚本</strong>
                    <p>搜索团队保存的脚本，并选择一篇作为裂变基础。</p>
                    <button
                      type="button"
                      onClick={() => setPickerOpen(true)}
                    >
                      打开共享脚本库
                    </button>
                  </div>
                )}
              </div>
            )}

            {!canUseLibrary && (
              <p className="fission-permission-note">
                当前账号可使用粘贴输入；如需选择或保存共享脚本，请联系管理员开通“共享脚本库”权限。
              </p>
            )}

            <label className="fission-requirements">
              <span>
                补充创作要求 <small>选填</small>
              </span>
              <textarea
                value={requirements}
                onChange={(event) => {
                  invalidateResults();
                  setRequirements(event.target.value);
                }}
                maxLength={MAX_REQUIREMENTS_LENGTH}
                placeholder="例如：用于抖音，面向职场新人，控制在 60 秒，语气更直接，强化收藏动机…"
                aria-label="补充创作要求"
              />
              <small>
                {requirements.length} / {MAX_REQUIREMENTS_LENGTH}
              </small>
            </label>

            {error && (
              <p className="fission-inline-error" role="alert">
                <AlertCircle size={16} /> {error}
              </p>
            )}

            <div className="fission-source-actions">
              {hasActiveRequests ? (
                <button
                  type="button"
                  className="fission-cancel-button"
                  onClick={cancelRequests}
                >
                  <Square size={15} /> 取消生成
                </button>
              ) : (
                <button
                  type="button"
                  className="fission-generate-button"
                  onClick={() => void startFission()}
                  disabled={
                    preselecting ||
                    (sourceMode === "text"
                      ? !text.trim()
                      : !selectedScript)
                  }
                >
                  <Sparkles size={17} />{" "}
                  {plan ? "重新规划并生成" : "生成 3 个裂变脚本"}
                </button>
              )}
              <small>当前来源：{sourceLength.toLocaleString()} 字</small>
            </div>
          </section>

          <section className="fission-results-panel" aria-label="裂变结果">
            <div className="fission-panel-heading">
              <span>02</span>
              <div>
                <h2>三个创作版本</h2>
                <p>每个方向独立生成，可以分别重试、编辑和保存。</p>
              </div>
            </div>

            {planning ? (
              <div className="fission-planning-state" aria-live="polite">
                <span>
                  <LoaderCircle className="spin" size={27} />
                </span>
                <h3>正在规划三个差异化方向…</h3>
                <p>系统正在提炼核心事实，并拆分钩子与叙事结构。</p>
              </div>
            ) : !plan ? (
              <div className="fission-empty-state">
                <WandSparkles size={31} />
                <h3>准备好来源脚本后开始裂变</h3>
                <p>规划完成后，三个版本会在这里各自生成并依次出现。</p>
              </div>
            ) : (
              <div className="fission-variant-grid">
                {plan.directions.map((direction, index) => {
                  const item = variants[direction.id] ?? emptyVariant();
                  const savedCurrent =
                    item.saved?.title === item.title.trim() &&
                    item.saved?.body === item.body;
                  return (
                    <article
                      key={direction.id}
                      className={`fission-variant-card ${item.status}`}
                    >
                      <header>
                        <span>版本 {index + 1}</span>
                        <div>
                          <h3>{direction.name}</h3>
                          <p>{direction.angle}</p>
                        </div>
                      </header>
                      <details>
                        <summary>查看本方向创作策略</summary>
                        <dl>
                          <div>
                            <dt>开场钩子</dt>
                            <dd>{direction.hook_strategy}</dd>
                          </div>
                          <div>
                            <dt>叙事结构</dt>
                            <dd>{direction.structure_strategy}</dd>
                          </div>
                        </dl>
                      </details>

                      {item.status === "loading" ? (
                        <div className="fission-variant-loading">
                          <LoaderCircle className="spin" size={24} />
                          <strong>正在创作这个版本…</strong>
                          <p>完整脚本生成后会自动显示。</p>
                        </div>
                      ) : item.status === "error" ? (
                        <div className="fission-variant-error" role="alert">
                          <AlertCircle size={23} />
                          <strong>这个版本没有生成成功</strong>
                          <p>{item.error}</p>
                          <button
                            type="button"
                            onClick={() =>
                              void generateDirection(
                                direction,
                                plan,
                                sourcePayload,
                              )
                            }
                          >
                            <RefreshCw size={15} /> 单独重试
                          </button>
                        </div>
                      ) : (
                        <div className="fission-variant-editor">
                          <label>
                            <span>标题</span>
                            <input
                              value={item.title}
                              onChange={(event) =>
                                updateVariant(
                                  direction.id,
                                  "title",
                                  event.target.value,
                                )
                              }
                              maxLength={255}
                              aria-label={`版本 ${index + 1} 标题`}
                            />
                            <small>{item.title.length} / 255</small>
                          </label>
                          <label>
                            <span>正文</span>
                            <textarea
                              value={item.body}
                              onChange={(event) =>
                                updateVariant(
                                  direction.id,
                                  "body",
                                  event.target.value,
                                )
                              }
                              maxLength={MAX_SOURCE_LENGTH}
                              aria-label={`版本 ${index + 1} 正文`}
                            />
                            <small>
                              {item.body.length.toLocaleString()} /{" "}
                              {MAX_SOURCE_LENGTH.toLocaleString()} 字
                            </small>
                          </label>

                          {item.error && (
                            <p className="fission-inline-error" role="alert">
                              {item.error}
                            </p>
                          )}

                          <footer>
                            <button
                              type="button"
                              onClick={() => void copyVariant(direction.id)}
                            >
                              {item.copied ? (
                                <Check size={15} />
                              ) : (
                                <Copy size={15} />
                              )}
                              {item.copied ? "已复制" : "复制脚本"}
                            </button>
                            {canUseLibrary && (
                              savedCurrent && item.saved ? (
                                <Link
                                  to={`/script-library/${encodeURIComponent(
                                    item.saved.id,
                                  )}`}
                                >
                                  <Check size={15} /> 已保存，查看脚本
                                </Link>
                              ) : (
                                <button
                                  type="button"
                                  className="primary"
                                  onClick={() => void saveVariant(direction.id)}
                                  disabled={item.saving}
                                >
                                  {item.saving ? (
                                    <LoaderCircle
                                      className="spin"
                                      size={15}
                                    />
                                  ) : (
                                    <Save size={15} />
                                  )}
                                  {item.saving
                                    ? "保存中…"
                                    : item.saved
                                      ? "另存为新脚本"
                                      : "保存到脚本库"}
                                </button>
                              )
                            )}
                          </footer>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </main>

      {pickerOpen && (
        <LibraryPicker
          onClose={() => setPickerOpen(false)}
          onSelect={chooseScript}
        />
      )}
    </AppShell>
  );
}
