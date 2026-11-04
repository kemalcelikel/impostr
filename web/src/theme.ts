import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
export const THEME_STORAGE_KEY = "impostr.theme";
const systemQuery = "(prefers-color-scheme: dark)";

function validTheme(value: string | null): Theme | null {
  return value === "light" || value === "dark" ? value : null;
}

export function createThemeStore(browser: Window) {
  let preference: Theme | null = null;
  try {
    preference = validTheme(browser.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    // Keep explicit choices in memory even when browser storage is unavailable.
  }
  const media = browser.matchMedia?.(systemQuery);
  let theme: Theme = preference ?? (media?.matches ? "dark" : "light");
  const listeners = new Set<() => void>();

  function applyTheme() {
    const root = browser.document.documentElement;
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    // The blocking bootstrap supplies a temporary background; CSS now owns it.
    root.style.removeProperty("background-color");
    const canvas = browser.getComputedStyle(root).getPropertyValue("--theme-canvas").trim();
    if (canvas) {
      browser.document.querySelector('meta[name="theme-color"]')?.setAttribute("content", canvas);
    }
  }

  function update(next: Theme) {
    const changed = theme !== next;
    theme = next;
    applyTheme();
    if (changed) listeners.forEach((listener) => listener());
  }

  function followSystem() {
    if (preference === null) update(media?.matches ? "dark" : "light");
  }

  function onStorage(event: StorageEvent) {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    // Ignore sessionStorage events (and tolerate restricted localStorage access).
    try {
      if (event.storageArea && event.storageArea !== browser.localStorage) return;
    } catch {
      return;
    }
    preference = validTheme(event.newValue);
    update(preference ?? (media?.matches ? "dark" : "light"));
  }

  applyTheme();

  return {
    getSnapshot: () => theme,
    setTheme(next: Theme) {
      preference = next;
      try {
        browser.localStorage.setItem(THEME_STORAGE_KEY, next);
      } catch {
        // The current page still honors the selection.
      }
      update(next);
    },
    subscribe(listener: () => void) {
      if (listeners.size === 0) {
        media?.addEventListener("change", followSystem);
        browser.addEventListener("storage", onStorage);
        followSystem();
      }
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          media?.removeEventListener("change", followSystem);
          browser.removeEventListener("storage", onStorage);
        }
      };
    },
  };
}

let store: ReturnType<typeof createThemeStore> | undefined;

export function initializeTheme() {
  store ??= createThemeStore(window);
  return store;
}

const subscribe = (listener: () => void) => initializeTheme().subscribe(listener);
const getSnapshot = () => initializeTheme().getSnapshot();

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot);
  return { theme, setTheme: initializeTheme().setTheme };
}
