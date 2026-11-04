import type { ComponentProps, ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export type ButtonProps = ComponentProps<"button"> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  icon?: IconName;
};

export function Button({
  variant = "secondary",
  icon,
  type = "button",
  className = "",
  children,
  ...props
}: ButtonProps) {
  return (
    <button {...props} className={`ui-button ui-button--${variant} ${className}`} type={type}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  icon,
  className = "",
  ...props
}: Omit<ButtonProps, "children" | "icon" | "aria-label"> & { label: string; icon: IconName }) {
  return (
    <Button
      {...props}
      aria-label={label}
      className={`ui-icon-button ${className}`}
      icon={icon}
      title={props.title ?? label}
    />
  );
}

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
}) {
  // Pair a control's aria-describedby with `${id}-hint` / `${id}-error` as needed.
  return (
    <div className="ui-field">
      <label className="ui-label" htmlFor={id}>
        {label}
      </label>
      {children}
      {hint ? (
        <p className="ui-field-hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="ui-field-error" id={`${id}-error`}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function Input({ className = "", ...props }: ComponentProps<"input">) {
  return <input {...props} className={`ui-input ${className}`} />;
}

export function Select({ className = "", ...props }: ComponentProps<"select">) {
  return <select {...props} className={`ui-input ${className}`} />;
}

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";
const toneIcons: Record<Tone, IconName> = {
  neutral: "info",
  info: "info",
  success: "check",
  warning: "alert",
  danger: "alert",
};

export function Badge({
  tone = "neutral",
  icon,
  className = "",
  children,
  ...props
}: ComponentProps<"span"> & { tone?: Tone; icon?: IconName }) {
  return (
    <span {...props} className={`ui-badge ui-tone--${tone} ${className}`}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </span>
  );
}

export function Feedback({
  tone = "info",
  className = "",
  children,
  ...props
}: ComponentProps<"div"> & { tone?: Tone }) {
  return (
    <div {...props} className={`ui-feedback ui-tone--${tone} ${className}`}>
      <Icon name={toneIcons[tone]} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function Disclosure({
  title,
  icon,
  className = "",
  children,
  ...props
}: Omit<ComponentProps<"details">, "title"> & { title: ReactNode; icon?: IconName }) {
  return (
    <details {...props} className={`ui-disclosure ${className}`}>
      <summary>
        {icon ? <Icon name={icon} /> : null}
        <span className="min-w-0 flex-1">{title}</span>
        <Icon className="ui-disclosure-chevron" name="chevronDown" />
      </summary>
      {children}
    </details>
  );
}

// Visual/semantic tab primitive only. The owning tablist manages keyboard roving,
// aria-controls, ids and mounted panels; this must not introduce navigation state.
export function TabButton({
  selected,
  className = "",
  ...props
}: Omit<ButtonProps, "role" | "aria-selected" | "variant"> & { selected: boolean }) {
  return (
    <Button
      {...props}
      aria-selected={selected}
      className={`ui-tab ${className}`}
      role="tab"
      tabIndex={props.tabIndex ?? (selected ? 0 : -1)}
      variant="ghost"
    />
  );
}
