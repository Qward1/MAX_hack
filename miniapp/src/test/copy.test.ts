import { readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import {
  residentIncidentStatus,
  residentTicketStatus,
  signalStatus,
  staffTicketStatus,
} from "../shared/ui/status";

/**
 * Тексты интерфейса — строки и JSX-текст всех исходников (без тестов,
 * сгенерированной схемы и комментариев). Разбор через TypeScript, а не
 * поиск по файлу: комментарии и имена в коде не мешают проверке.
 */
const FILES = Object.entries(
  import.meta.glob(
    ["../**/*.{ts,tsx}", "!../**/*.test.{ts,tsx}", "!../shared/api/schema.ts", "!../test/**", "!../**/*.d.ts"],
    { query: "?raw", import: "default", eager: true },
  ) as Record<string, string>,
).map(([path, code]) => ({ path: path.replace(/^\.\.\//, ""), code }));

function texts(file: { path: string; code: string }): string[] {
  const source = ts.createSourceFile(
    file.path,
    file.code,
    ts.ScriptTarget.Latest,
    true,
    file.path.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const found: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) found.push(node.text);
    else if (ts.isTemplateExpression(node))
      found.push([node.head.text, ...node.templateSpans.map((span) => span.literal.text)].join(" "));
    else if (ts.isJsxText(node) && node.text.trim()) found.push(node.text.replace(/\s+/g, " "));
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found.filter((text) => /[а-яё]/i.test(text));
}

/** Единый список запрещённых формулировок — из backend, без копии во frontend. */
function forbiddenPhrases(): string[] {
  // Тесты запускаются из каталога miniapp (npm run test, check.py --scope frontend).
  const python = readFileSync("../src/domsignal/services/action_cards.py", "utf8");
  const block = /FORBIDDEN_PHRASES[^=]*=\s*\(([\s\S]*?)\)/.exec(python)?.[1] ?? "";
  return [...block.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
}

// Синонимы, которые UX-1 тоже не пропускает во frontend: факт передачи или
// регистрации без события системы.
const SYNONYMS = ["передана в", "передан в", "направлено в", "направлена в", "обращение подано", "обращение принято"];

describe("честность текстов интерфейса", () => {
  it("читает список запрещённых формулировок из backend", () => {
    const list = forbiddenPhrases();
    expect(list).toContain("заявка отправлена");
    expect(list).toContain("обращение зарегистрировано");
    expect(list).toContain("передано в");
  });

  it("ни один текст интерфейса не утверждает отправку или регистрацию без события системы", () => {
    const phrases = [...forbiddenPhrases(), ...SYNONYMS];
    expect(FILES.length).toBeGreaterThan(30);
    const offenders = FILES.flatMap((file) =>
      texts(file)
        .filter((text) => phrases.some((phrase) => text.toLowerCase().includes(phrase)))
        .map((text) => `${file.path}: ${text}`),
    );
    expect(offenders).toEqual([]);
  });

  it("на экранах жителя нет внутренних слов: инцидент, сигнал, маршрут, канал", () => {
    const resident = FILES.filter(
      // Строки сотрудника в общем модуле заявок (попытки, история) жителю не показываются.
      (file) => /^(app|features)\//.test(file.path) && file.path !== "features/tickets/components.tsx",
    );
    expect(resident.length).toBeGreaterThan(10);
    const internal = /инцидент|(?<!Дом)сигнал|маршрут|(^|[^а-яё])канал/i;
    const offenders = resident.flatMap((file) =>
      texts(file)
        .filter((text) => internal.test(text))
        .map((text) => `${file.path}: ${text}`),
    );
    expect(offenders).toEqual([]);
  });

  it("словари статусов жителя говорят словами жителя и описывают состояние", () => {
    for (const entry of [...Object.values(residentIncidentStatus), ...Object.values(residentTicketStatus)]) {
      expect(entry.label).not.toMatch(/инцидент|сигнал|маршрут|канал|ticket|incident/i);
      // Подпись — состояние, а не команда: «В работе», а не «Проверьте».
      expect(entry.label).not.toMatch(/^(Проверьте|Сообщите|Нажмите|Откройте)/);
    }
  });

  it("в словарях нет обещаний, которых система не знает", () => {
    const all = [residentIncidentStatus, residentTicketStatus, staffTicketStatus, signalStatus].flatMap((dictionary) =>
      Object.values(dictionary).flatMap((entry) => [entry.label, entry.next ?? ""]),
    );
    const phrases = [...forbiddenPhrases(), ...SYNONYMS];
    expect(all.filter((text) => phrases.some((phrase) => text.toLowerCase().includes(phrase)))).toEqual([]);
    expect(all.filter((text) => /\d+\s*(дн|час|рабоч)/.test(text))).toEqual([]);
  });
});
