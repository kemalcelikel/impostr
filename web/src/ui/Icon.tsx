import type { SVGProps } from "react";

// Original 24px outline family: 1.75px strokes, shared caps and joins.
const paths = {
  sun: "M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17m10-10 1.4-1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  moon: "M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  eyeOff:
    "m3 3 18 18M10 5.2A12 12 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 4M6 6.5A19 19 0 0 0 2 12s3.5 7 10 7a11 11 0 0 0 5-1.2M10 10a3 3 0 0 0 4 4",
  logIn: "M14 4h5v16h-5M3 12h12m-4-4 4 4-4 4",
  logOut: "M10 4H5v16h5m2-8h9m-4-4 4 4-4 4",
  user: "M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-2a8 8 0 0 1 16 0v2",
  userPlus: "M14 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM2 21v-2a8 8 0 0 1 12-6.9M18 14v8m-4-4h8",
  shield: "m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Zm-4 9 3 3 5-6",
  lock: "M7 10V7a5 5 0 0 1 10 0v3M5 10h14v11H5V10Zm7 5v2",
  key: "M11 8a5 5 0 1 1-10 0 5 5 0 0 1 10 0Zm0 0h11m-3 0v4m-4-4v3",
  check: "m5 12 4 4L19 6",
  alert: "m12 3 10 18H2L12 3Zm0 6v5m0 3v.1",
  info: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Zm-10-1v6m0-10v.1",
  refresh: "M20 9a8 8 0 0 0-14-3L3 9m0-5v5h5m-4 6a8 8 0 0 0 14 3l3-3m0 5v-5h-5",
  close: "m6 6 12 12M6 18 18 6",
  chevronDown: "m6 9 6 6 6-6",
  chevronLeft: "m15 6-6 6 6 6",
  chevronRight: "m9 6 6 6-6 6",
  folder: "M3 5h6l2 3h10v12H3V5Z",
  document: "M5 3h9l5 5v13H5V3Zm9 0v5h5M9 12h6m-6 4h6",
  history: "M3 10a9 9 0 1 1 1 7M3 4v6h6m3-3v5l3 2",
  attachment: "m8 13 7-7a3 3 0 0 1 4 4L9 20a5 5 0 0 1-7-7L13 2",
  download: "M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5",
  save: "M4 3h13l3 3v15H4V3Zm4 0v6h8V3M8 21v-8h8v8",
  chat: "M3 4h18v13H9l-6 4V4Z",
  canvas: "M3 3h7v7H3V3Zm11 0h7v7h-7V3ZM3 14h7v7H3v-7Zm11 0h7v7h-7v-7Z",
  plus: "M12 4v16M4 12h16",
  arrowLeft: "M20 12H4m6-6-6 6 6 6",
  arrowUp: "M12 20V4m-6 6 6-6 6 6",
  arrowDown: "M12 4v16m-6-6 6 6 6-6",
  arrowRight: "M4 12h16m-6-6 6 6-6 6",
  zoomIn: "M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5 6 6M7 10h6m-3-3v6",
  zoomOut: "M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5 6 6M7 10h6",
  fitView: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M8 8h8v8H8V8Z",
  grip: "M9 5v.1m6-.1v.1M9 12v.1m6-.1v.1M9 19v.1m6-.1v.1",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7",
} satisfies Record<string, string>;

export type IconName = keyof typeof paths;

// Glyphs are decorative; the owning control or adjacent text provides the name.
export function Icon({
  name,
  className = "",
  ...props
}: Omit<SVGProps<SVGSVGElement>, "children" | "name"> & { name: IconName }) {
  return (
    <svg
      {...props}
      aria-hidden="true"
      className={`ui-icon ${className}`}
      fill="none"
      focusable="false"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.75"
      viewBox="0 0 24 24"
    >
      <path d={paths[name]} />
    </svg>
  );
}
