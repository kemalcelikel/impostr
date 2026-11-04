/// <reference types="node" />
import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Brand } from "./Brand";

const originalM = "M4 14.5V5.5h3.25l2.75 4 2.75-4H16v9h-3V9.8l-3 4.1-3-4.1v4.7H4Z";
const source = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
});

describe("original Impostr identity", () => {
  it("retains the exact glyph, backing and capitalized wordmark across themes", () => {
    const { container } = render(<Brand />);
    const mark = container.querySelector("svg")!;
    for (const theme of ["light", "dark"]) {
      document.documentElement.dataset.theme = theme;
      expect(screen.getByText("Impostr")).toBeInTheDocument();
      expect(container.querySelector("svg")).toBe(mark);
      expect(mark).toHaveAttribute("viewBox", "0 0 20 20");
      expect(mark).toHaveAttribute("aria-hidden", "true");
      expect(mark.querySelector("path")).toHaveAttribute("d", originalM);
      expect(mark.querySelector("path")).toHaveAttribute("fill", "#8ee2aa");
      expect(mark.querySelector("rect")).toHaveAttribute("fill", "#19251e");
    }
    const css = source("src/index.css");
    expect(css.match(/--brand-ink:\s*#[\da-f]+/gi)).toEqual(["--brand-ink: #8ee2aa"]);
    expect(css.match(/--brand-ground:\s*#[\da-f]+/gi)).toEqual(["--brand-ground: #19251e"]);
    expect(css).toContain("fill: var(--brand-ink)");
    expect(css).toContain("fill: var(--brand-ground)");
  });

  it("links a standalone favicon with the same M and backing, without external assets", () => {
    const html = new DOMParser().parseFromString(source("index.html"), "text/html");
    const icon = html.querySelector('link[rel="icon"]');
    expect(icon?.getAttribute("href")).toBe("/favicon.svg");
    expect(icon?.getAttribute("type")).toBe("image/svg+xml");
    const favicon = new DOMParser().parseFromString(source("public/favicon.svg"), "image/svg+xml");
    expect(favicon.querySelector("parsererror")).toBeNull();
    expect(favicon.documentElement.localName).toBe("svg");
    expect(favicon.documentElement.getAttribute("viewBox")).toBe("0 0 20 20");
    expect(favicon.querySelector("path")?.getAttribute("d")).toBe(originalM);
    expect(favicon.querySelector("path")?.getAttribute("fill")).toBe("#8ee2aa");
    expect(favicon.querySelector("rect")?.getAttribute("fill")).toBe("#19251e");
    expect(favicon.querySelector("image, use, script")).toBeNull();
  });
});
