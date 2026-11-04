import "@testing-library/jest-dom/vitest";
import { createRef, type FormEvent } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Badge,
  Button,
  Disclosure,
  Feedback,
  Field,
  IconButton,
  Input,
  Select,
  TabButton,
} from "./controls";

afterEach(cleanup);

describe("shared controls", () => {
  it("preserves native submission, disabled behavior, labels, and DOM refs", () => {
    const submit = vi.fn((event: FormEvent) => event.preventDefault());
    const cancel = vi.fn();
    const ref = createRef<HTMLButtonElement>();
    render(
      <form onSubmit={submit}>
        <Button icon="save" ref={ref} type="submit" variant="primary">
          Save draft
        </Button>
        <Button onClick={cancel}>Cancel</Button>
        <Button disabled icon="trash" onClick={cancel} variant="danger">
          Delete draft
        </Button>
      </form>,
    );
    expect(ref.current).toBe(screen.getByRole("button", { name: "Save draft" }));
    expect(ref.current?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(submit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Delete draft" }));
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Delete draft" })).toBeDisabled();
  });

  it("gives icon-only actions a name and forwards pressed/controlled state", () => {
    render(<IconButton aria-controls="history" aria-pressed icon="history" label="Show history" />);
    const button = screen.getByRole("button", { name: "Show history" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveAttribute("aria-controls", "history");
    expect(button.querySelector("svg")).toHaveAttribute("focusable", "false");
  });

  it("keeps field labels, constraints, descriptions and native select behavior", () => {
    const onChange = vi.fn();
    render(
      <>
        <Field
          error="Use at least 12 characters."
          hint="Paste is supported."
          id="password"
          label="Password"
        >
          <Input
            aria-describedby="password-hint password-error"
            aria-invalid
            autoComplete="new-password"
            id="password"
            maxLength={256}
            minLength={12}
            required
            type="password"
          />
        </Field>
        <Field id="role" label="Role">
          <Select defaultValue="member" id="role" onChange={onChange}>
            <option value="member">Member</option>
            <option value="admin">Administrator</option>
          </Select>
        </Field>
      </>,
    );
    const password = screen.getByLabelText("Password");
    expect(password).toBeRequired();
    expect(password).toHaveAttribute("minlength", "12");
    expect(password).toHaveAttribute("maxlength", "256");
    expect(password).toHaveAttribute("autocomplete", "new-password");
    expect(password).toHaveAccessibleDescription("Paste is supported. Use at least 12 characters.");
    fireEvent.change(screen.getByRole("combobox", { name: "Role" }), {
      target: { value: "admin" },
    });
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveValue("admin");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("preserves disclosure semantics, tab state, and caller-owned live feedback", () => {
    render(
      <>
        <Disclosure icon="key" title="Reset password">
          <p>Reset form</p>
        </Disclosure>
        <div role="tablist">
          <TabButton aria-controls="project-panel" icon="document" selected>
            Project
          </TabButton>
          <TabButton aria-controls="history-panel" selected={false}>
            History
          </TabButton>
        </div>
        <Badge icon="check" tone="success">
          Approved
        </Badge>
        <Feedback aria-live="assertive" role="alert" tone="danger">
          Save failed; draft retained.
        </Feedback>
      </>,
    );
    expect(screen.getByText("Reset password").closest("summary")?.parentElement?.tagName).toBe(
      "DETAILS",
    );
    expect(screen.getByRole("tab", { name: "Project" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Project" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("alert")).toHaveTextContent("Save failed; draft retained.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });
});
