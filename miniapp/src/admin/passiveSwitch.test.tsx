import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Schema } from "./administration";
import { PassiveSwitch } from "./CompanyPages";

const binding = {
  id: "binding-1",
  passive_capture_enabled: true,
} as unknown as Schema["ChatSummary"];

function renderSwitch(aiAnalysis: boolean, enabled = true) {
  return render(
    <PassiveSwitch
      binding={{ ...binding, passive_capture_enabled: enabled }}
      available
      aiAnalysis={aiAnalysis}
      busy={false}
      confirming={false}
      ask={() => undefined}
      cancel={() => undefined}
      change={async () => undefined}
    />,
  );
}

describe("PassiveSwitch (P6b): режим разбора переписки", () => {
  it("показывает модель, когда она разбирает окна чата", () => {
    renderSwitch(true);
    expect(screen.getByText("Разбор переписки: правила и модель (ИИ)")).toBeTruthy();
  });

  it("показывает только правила, когда модель в чатах выключена", () => {
    renderSwitch(false);
    expect(
      screen.getByText("Разбор переписки: только правила, модель в чатах выключена"),
    ).toBeTruthy();
  });

  it("не показывает режим, пока чтение чата выключено", () => {
    renderSwitch(true, false);
    expect(screen.queryByText(/Разбор переписки/)).toBeNull();
  });
});
