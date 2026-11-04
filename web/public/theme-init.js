// A same-origin, parser-blocking script: resolve the theme before the first paint.
// Keep the storage key and the two temporary canvas colors aligned with theme.ts/index.css.
(() => {
  let preference = null;
  try {
    const stored = window.localStorage.getItem("impostr.theme");
    if (stored === "light" || stored === "dark") preference = stored;
  } catch {
    // Private/blocked storage must not prevent the application from starting.
  }
  const dark =
    preference === "dark" ||
    (preference === null && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  const theme = dark ? "dark" : "light";
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  // This temporary background covers the time before Vite's stylesheet arrives.
  root.style.backgroundColor = dark ? "#121815" : "#f3f4f0";
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#121815" : "#f3f4f0");
})();
