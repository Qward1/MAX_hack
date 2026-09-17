import { MaxUI } from "@maxhub/max-ui";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import { IncidentCard } from "../../features/incidents/IncidentCard";
import {
  categoryLabel,
  knownActions,
  ruleSource,
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
            type,
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
          .getByRole("link", { name: "Открыть источник ↗" })
          .getAttribute("href"),
      ).toBe("https://example.org/rule");
    },
  );
  it("does not show a missing source or bless incomplete official data", () => {
    const { rerender, container } = render(<SourceChip source={null} />);
    expect(container.textContent).toBe("");
    rerender(
      <SourceChip
        source={{ type: "official", source_url: "javascript:alert(1)" }}
      />,
    );
    expect(screen.getByText("Происхождение не подтверждено")).toBeTruthy();
    expect(screen.queryByRole("link", { hidden: true })).toBeNull();
  });
  it("never maps verified C0 rules to official provenance", () => {
    expect(
      ruleSource({ ...incident.rule, verification_status: "verified" })?.type,
    ).toBe("unknown");
    expect(ruleSource(null)).toBeNull();
  });
  it("unknown category uses a generic name", () => {
    expect(categoryLabel("future")).toBe("Другая проблема дома");
  });
  it.each([0, 1, 9999])(
    "renders message count %i without claiming unique residents",
    (count) => {
      render(
        <IncidentCard
          incident={{ ...incident, report_count: count }}
          href="/?incident=id"
          onNavigate={vi.fn()}
        />,
      );
      expect(screen.getByText(`Сообщений: ${count}`)).toBeTruthy();
    },
  );
  it("keeps long description and safe defaults", () => {
    const description = "Большойтекст".repeat(100);
    render(
      <IncidentCard
        incident={{ ...incident, title: "Адрес".repeat(50), description }}
        href="/"
        onNavigate={vi.fn()}
      />,
    );
    expect(screen.getByText(description)).toBeTruthy();
  });
  it("does not show view action when permission is absent", () => {
    render(
      <IncidentCard
        incident={{ ...incident, allowed_actions: [] }}
        href="/"
        onNavigate={vi.fn()}
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
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
  it("only legacy view string grants permission", () => {
    expect(knownActions(["prepare_appeal", "__proto__", "view"])).toEqual([
      { code: "view", enabled: true, reason: null },
    ]);
  });
  it("passes axe semantic smoke checks", async () => {
    const { container } = render(
      <MaxUI>
        <main>
          <h1>Дом</h1>
          <NextAction actions={[]} />
          <IncidentCard incident={incident} href="/" onNavigate={vi.fn()} />
        </main>
      </MaxUI>,
    );
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  });
});
