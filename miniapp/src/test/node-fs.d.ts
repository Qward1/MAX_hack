// Тестам нужно одно чтение файла из Node (vitest), а зависимостей @types/node в
// проекте нет и добавлять их нельзя: объявляем только то, что используем.
declare module "node:fs" {
  export function readFileSync(path: URL | string, encoding: "utf8"): string;
}
