import { MaxUI } from "@maxhub/max-ui";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import { IncidentRow } from "../../features/incidents/IncidentCard";
import {
  categoryLabel,
  knownActions,
  statusLabels,
} from "../../features/incidents/presentation";
import { incident } from "../../test/fixtures";
import { NextAction, SourceChip, StatusBadge } from "./semantic";

describe("semantic presentation", () => {
  it.each(Object.entries(statusLabels))(
    "renders status %s without inventing registration",
    (status, label) => {
      render(<StatusBadge status={status} />);
      expect(screen.getByText(label)).toBeTruthy();
    },
  );
  it("unknown status is neutral and never logs server content", () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    render(<StatusBadge status="private-new-state" />);
    expect(screen.getByText("Состояние обновилось").className).toContain(
      "neutral",
    );
    expect(warning.mock.calls.flat().join()).not.toContain("private-new-state");
  });
  it.each(["official", "product_derived", "user_reported", "demo", "future"])(
    "source %s has keyboard disclosure and safe link",
    async (type) => {
      const user = userEvent.setup();
      render(
        <SourceChip
          source={{
            origin: type,
            source_title: "Источник",
            source_url: "https://example.org/rule",
            verified_at: "2026-01-01T12:00:00Z",
            note: "Основание",
          }}
        />,
      );
      // jsdom does not implement keyboard activation for native summary; browser suite covers it.
      const summary = document.querySelector("summary")!;
      await user.click(summary);
      expect(document.querySelector("details")?.open).toBe(true);
      expect(
        screen
          .getByRole("link", { name: /^Открыть источник/ })
          .getAttribute("href"),
      ).toBe("https://example.org/rule");
    },
  );
  it("does not show a missing source or bless incomplete official data", () => {
    const { rerender, container } = render(<SourceChip source={null} />);
    expect(container.textContent).toBe("");
    rerender(
      <SourceChip
        source={{ origin: "official", source_url: "javascript:alert(1)" }}
      />,
    );
    expect(screen.getByText(/Происхождение не подтверждено/)).toBeTruthy();
    expect(screen.queryByRole("link", { hidden: true })).toBeNull();
  });
  it("verification does not determine origin", () => {
    render(<SourceChip source={{ ...incident.rule, origin: null, verified_at: "2026-01-01T12:00:00Z" }} />);
    expect(screen.queryByText(/Официальный источник/)).toBeNull();
    expect(screen.getByText(/Происхождение не подтверждено/)).toBeTruthy();
  });
  it("unknown category uses a generic name", () => {
    expect(categoryLabel("future")).toBe("Другая проблема дома");
  });
  it.each([
    [1, "1 сосед"],
    [3, "3 соседа"],
    [5, "5 соседей"],
    [11, "11 соседей"],
    [21, "21 сосед"],
  ])("counts %i neighbours with the right Russian form", (count, text) => {
    render(
      <IncidentRow
        incident={{ ...incident, participant_count: count, report_count: 99 }}
        href="/?incident=id"
        onNavigate={vi.fn()}
      />,
    );
    expect(screen.getByText(new RegExp(text))).toBeTruthy();
  });
  it("does not claim unique residents when the count is unknown", () => {
    render(
      <IncidentRow
        incident={{ ...incident, participant_count: null, report_count: 7 }}
        href="/?incident=id"
        onNavigate={vi.fn()}
      />,
    );
    expect(screen.queryByText(/сосед/)).toBeNull();
  });
  it("keeps long description and safe defaults", () => {
    const description = "Большойтекст".repeat(100);
    render(
      <IncidentRow
        incident={{ ...incident, title: "Адрес".repeat(50), description }}
        href="/"
        onNavigate={vi.fn()}
      />,
    );
    expect(screen.getByText(description)).toBeTruthy();
  });
  it("opens a returned resource even with no domain actions", () => {
    render(
      <IncidentRow
        incident={{ ...incident, allowed_actions: [] }}
        href="/"
        onNavigate={vi.fn()}
      />,
    );
    expect(screen.getByRole("link")).toBeTruthy();
  });
  it("uses explicit permissions, disables with reason and ignores unknown actions", () => {
    const handler = vi.fn();
    const { rerender } = render(
      <NextAction
        actions={[{ code: "prepare_appeal", enabled: true }]}
        handlers={{ prepare_appeal: handler }}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Подготовить обращение" }),
    );
    expect(handler).toHaveBeenCalledTimes(1);
    rerender(
      <NextAction
        actions={[
          {
            code: "prepare_appeal",
            enabled: false,
            reason: "Срок ещё не истёк",
          },
          { code: "future", enabled: true },
        ]}
        handlers={{ prepare_appeal: handler }}
      />,
    );
    const button = screen.getByRole("button", {
      name: "Подготовить обращение",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Срок ещё не истёк")).toBeTruthy();
    expect(screen.queryByText("future")).toBeNull();
  });
  it("a known action without an implemented handler is never advertised", () => {
    render(
      <NextAction actions={[{ code: "prepare_appeal", enabled: true }]} />,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("legacy strings grant no domain permission", () => {
    expect(knownActions(["prepare_appeal", "__proto__", "view"])).toEqual([]);
  });
  it("passes axe semantic smoke checks", async () => {
    const { container } = render(
      <MaxUI>
        <main>
          <h1>Дом</h1>
          <NextAction actions={[]} />
          <IncidentRow incident={incident} href="/" onNavigate={vi.fn()} />
        </main>
      </MaxUI>,
    );
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });
});
