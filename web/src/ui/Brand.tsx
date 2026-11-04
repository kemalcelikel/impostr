// Keep the original 20px M and its backing independent of theme/action colors.
export function Brand() {
  return (
    <span className="brand">
      <svg aria-hidden="true" className="brand-mark" focusable="false" viewBox="0 0 20 20">
        <rect className="brand-ground" width="20" height="20" rx="4" fill="#19251e" />
        <path
          className="brand-ink"
          d="M4 14.5V5.5h3.25l2.75 4 2.75-4H16v9h-3V9.8l-3 4.1-3-4.1v4.7H4Z"
          fill="#8ee2aa"
        />
      </svg>
      <span className="brand-name">Impostr</span>
    </span>
  );
}
