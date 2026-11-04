/// <reference types="node" />

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createThemeStore, THEME_STORAGE_KEY } from "./theme";

// npm/Vitest runs from the web root (/web in the pinned checks target).
// Load only the checked-in bootstrap, without Vite/jsdom's browser URL rewriting.
const bootstrap = readFileSync(resolve(process.cwd(), "public/theme-init.js"), "utf8");
const stylesheet = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");
const unsubscribers: (() => void)[] = [];

function systemPreference(dark: boolean) {
  const media = new EventTarget();
  const query = Object.assign(media, { matches: dark });
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => query),
  );
  return (next: boolean) => {
    query.matches = next;
    query.dispatchEvent(new Event("change"));
  };
}

afterEach(() => {
  unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
  document.querySelector('meta[name="theme-color"]')?.remove();
});

describe("browser theme preference", () => {
  it("follows system changes until an explicit choice, even when choosing the current theme", () => {
    const changeSystem = systemPreference(true);
    const store = createThemeStore(window);
    const notify = vi.fn();
    unsubscribers.push(store.subscribe(notify));
    expect(store.getSnapshot()).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();

    changeSystem(false);
    expect(store.getSnapshot()).toBe("light");
    expect(notify).toHaveBeenCalledTimes(1);
    store.setTheme("light");
    changeSystem(true);
    expect(store.getSnapshot()).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(createThemeStore(window).getSnapshot()).toBe("light");
  });

  it.each(["light", "dark"] as const)(
    "restores an explicit %s selection over the system",
    (theme) => {
      systemPreference(theme !== "dark");
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
      expect(createThemeStore(window).getSnapshot()).toBe(theme);
    },
  );

  it("ignores invalid saved values and tolerates a browser without matchMedia", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "unexpected");
    vi.stubGlobal("matchMedia", undefined);
    expect(createThemeStore(window).getSnapshot()).toBe("light");
  });

  it("tolerates blocked storage access and retains an explicit selection in memory", () => {
    const changeSystem = systemPreference(true);
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    const store = createThemeStore(window);
    unsubscribers.push(store.subscribe(vi.fn()));
    expect(store.getSnapshot()).toBe("dark");
    expect(() => store.setTheme("light")).not.toThrow();
    changeSystem(false);
    changeSystem(true);
    expect(store.getSnapshot()).toBe("light");
  });

  it("tolerates a failed storage write and releases listeners after unmount", () => {
    const changeSystem = systemPreference(false);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Full", "QuotaExceededError");
    });
    const store = createThemeStore(window);
    const notify = vi.fn();
    const unsubscribe = store.subscribe(notify);
    store.setTheme("dark");
    expect(store.getSnapshot()).toBe("dark");
    unsubscribe();
    window.dispatchEvent(
      new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: "light" }),
    );
    changeSystem(false);
    expect(notify).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot()).toBe("dark");
  });

  it("syncs explicit choices across tabs and resumes system following when cleared", () => {
    const changeSystem = systemPreference(false);
    const store = createThemeStore(window);
    unsubscribers.push(store.subscribe(vi.fn()));
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: THEME_STORAGE_KEY,
        newValue: "dark",
        storageArea: window.localStorage,
      }),
    );
    expect(store.getSnapshot()).toBe("dark");
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: THEME_STORAGE_KEY,
        newValue: "light",
        storageArea: window.sessionStorage,
      }),
    );
    expect(store.getSnapshot()).toBe("dark");
    window.dispatchEvent(new StorageEvent("storage", { key: THEME_STORAGE_KEY, newValue: null }));
    expect(store.getSnapshot()).toBe("light");
    changeSystem(true);
    expect(store.getSnapshot()).toBe("dark");
  });
});

describe("pre-paint bootstrap", () => {
  it.each([
    { saved: "dark", systemDark: false, expected: "dark" },
    { saved: "light", systemDark: true, expected: "light" },
    { saved: "invalid", systemDark: true, expected: "dark" },
    { saved: null, systemDark: false, expected: "light" },
  ])(
    "initializes $expected before React, in agreement with the runtime",
    ({ saved, systemDark, expected }) => {
      systemPreference(systemDark);
      if (saved !== null) window.localStorage.setItem(THEME_STORAGE_KEY, saved);
      const meta = document.createElement("meta");
      meta.name = "theme-color";
      document.head.append(meta);
      runInNewContext(bootstrap, { window, document });
      expect(document.documentElement.dataset.theme).toBe(expected);
      expect(document.documentElement.style.colorScheme).toBe(expected);
      expect(meta.content).toBe(expected === "dark" ? "#121815" : "#f3f4f0");
      const palette = stylesheet.match(
        expected === "dark" ? /:root\[data-theme="dark"\]\s*\{([^}]+)\}/ : /:root\s*\{([^}]+)\}/,
      )?.[1];
      expect(palette).toContain(`--theme-canvas: ${meta.content};`);
      expect(document.documentElement.style.backgroundColor).not.toBe("");
      expect(createThemeStore(window).getSnapshot()).toBe(expected);
      expect(document.documentElement.style.backgroundColor).toBe("");
    },
  );

  it("starts without storage or matchMedia and does not write a preference", () => {
    const blockedWindow = {
      get localStorage() {
        throw new DOMException("Blocked", "SecurityError");
      },
    };
    expect(() => runInNewContext(bootstrap, { window: blockedWindow, document })).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
