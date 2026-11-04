import { useTheme } from "../theme";
import { Button } from "./controls";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <Button
      aria-label={`Switch to ${next} mode`}
      icon={next === "light" ? "sun" : "moon"}
      onClick={() => setTheme(next)}
      title={`Current appearance: ${theme}. Switch to ${next} mode.`}
    >
      <span>{next === "light" ? "Light mode" : "Dark mode"}</span>
    </Button>
  );
}
