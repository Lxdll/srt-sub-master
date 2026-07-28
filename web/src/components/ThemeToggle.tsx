import { Moon, Sun } from "lucide-react";
import { useTheme } from "../lib/theme";

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { theme, toggleTheme } = useTheme();
  const dark = theme === "dark";

  return (
    <button
      className={`theme-toggle${compact ? " compact" : ""}`}
      type="button"
      onClick={toggleTheme}
      aria-pressed={dark}
      aria-label={dark ? "切换为亮色主题" : "切换为暗色主题"}
      title={dark ? "切换为亮色主题" : "切换为暗色主题"}
    >
      <Sun size={14} aria-hidden="true" />
      <span className="theme-toggle-track" aria-hidden="true">
        <span />
      </span>
      <Moon size={14} aria-hidden="true" />
    </button>
  );
}
