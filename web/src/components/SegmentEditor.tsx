import { Check, CircleAlert, LoaderCircle } from "lucide-react";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { api } from "../lib/api";
import type { Segment } from "../types";

interface SegmentEditorProps {
  taskId: string;
  segment: Segment;
  active: boolean;
  onSeek: (seconds: number) => void;
}

export interface SegmentEditorHandle {
  scrollIntoView: () => void;
}

export const SegmentEditor = forwardRef<
  SegmentEditorHandle,
  SegmentEditorProps
>(function SegmentEditor(
  { taskId, segment, active, onSeek },
  forwardedRef,
) {
  const rowRef = useRef<HTMLDivElement>(null);
  const [text, setText] = useState(segment.edited_text);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "error">(
    "saved",
  );

  useImperativeHandle(forwardedRef, () => ({
    scrollIntoView: () =>
      rowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
  }));

  useEffect(() => {
    setText(segment.edited_text);
  }, [segment.edited_text]);

  useEffect(() => {
    if (text === segment.edited_text) return;
    setSaveState("saving");
    const timer = window.setTimeout(() => {
      api
        .editSegment(taskId, segment.id, text)
        .then(() => setSaveState("saved"))
        .catch(() => setSaveState("error"));
    }, 500);
    return () => clearTimeout(timer);
  }, [text, segment.edited_text, segment.id, taskId]);

  return (
    <div
      ref={rowRef}
      className={`segment-row ${active ? "active" : ""}`}
      onClick={() => onSeek(segment.start_ms / 1000)}
    >
      <button className="segment-time" type="button">
        {formatTime(segment.start_ms)}
        <span>→</span>
        {formatTime(segment.end_ms)}
      </button>
      <textarea
        value={text}
        rows={Math.max(1, Math.ceil(text.length / 28))}
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => {
          setText(event.target.value);
        }}
        aria-label={`第 ${segment.ordinal + 1} 条字幕`}
      />
      <span className={`save-state ${saveState}`}>
        {saveState === "saving" && <LoaderCircle size={14} className="spin" />}
        {saveState === "saved" && <Check size={14} />}
        {saveState === "error" && <CircleAlert size={14} />}
        {saveState === "saving"
          ? "保存中"
          : saveState === "saved"
            ? "已保存"
            : "保存失败"}
      </span>
    </div>
  );
});

export function formatTime(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, "0")}:${seconds
    .toString()
    .padStart(2, "0")}.${Math.floor((milliseconds % 1000) / 100)}`;
}
