# Лицензии зависимостей

Срез D5, 27.09.2026. Списки собраны из установленных пакетов: Python — метаданные
окружения `uv sync --frozen --group dev` (`importlib.metadata`, отметка runtime —
по `uv export --no-dev`), npm — `npx license-checker-rseidelsohn@4.4.2` по
`miniapp/node_modules` после `npm ci` (отметка «прод» — `--production`).
Инструменты запускались через `uv`/`npx` и в lock-файлы не добавлены.

## Итог

- Python: 55 пакетов (42 runtime, 13 dev).
- npm: 131 пакет, из них в сборку мини-приложения попадают 8 (все MIT). Список снят на Windows: платформенные сборки (`lightningcss-win32-x64-msvc`, `@rollup/rollup-win32-*`) в Linux-образе заменяются своими `linux-x64` вариантами с той же лицензией.
- Несвободных лицензий нет. Слабый копилефт — MPL-2.0 (Python: certifi, pathspec; npm: axe-core, lightningcss, lightningcss-win32-x64-msvc) — используются без изменений, условие MPL о раскрытии изменённых файлов не затрагивается.

## Несвободные или неясные

Нет.

## Python

| Пакет | Версия | Лицензия | Где |
|---|---|---|---|
| alembic | 1.20.0 | MIT | runtime |
| annotated-doc | 0.0.5 | MIT | runtime |
| annotated-types | 0.8.0 | MIT | runtime |
| anyio | 4.15.1 | MIT | runtime |
| argon2-cffi | 25.1.0 | MIT | runtime |
| argon2-cffi-bindings | 26.1.0 | MIT | runtime |
| asyncpg | 0.31.0 | Apache-2.0 | runtime |
| attrs | 26.1.0 | MIT | runtime |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | runtime |
| cffi | 2.1.1 | MIT-0 | runtime |
| click | 8.5.0 | BSD-3-Clause | runtime |
| colorama | 0.4.6 | BSD License | runtime |
| cryptography | 48.0.1 | Apache-2.0 OR BSD-3-Clause | runtime |
| fastapi | 0.141.1 | MIT | runtime |
| greenlet | 3.5.6 | MIT AND PSF-2.0 | runtime |
| h11 | 0.16.0 | MIT License | runtime |
| httpcore | 1.0.9 | BSD-3-Clause | runtime |
| httptools | 0.8.0 | MIT | runtime |
| httpx | 0.28.1 | BSD License | runtime |
| idna | 3.19 | BSD-3-Clause | runtime |
| iniconfig | 2.3.0 | MIT | dev |
| jsonschema | 4.26.0 | MIT | runtime |
| jsonschema-specifications | 2025.9.1 | MIT | runtime |
| librt | 0.15.0 | MIT | dev |
| Mako | 1.4.1 | MIT | runtime |
| MarkupSafe | 3.0.3 | BSD-3-Clause | runtime |
| mypy | 1.20.2 | MIT | dev |
| mypy_extensions | 1.1.0 | MIT | dev |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | dev |
| pathspec | 1.1.1 | Mozilla Public License 2.0 (MPL 2.0) | dev |
| pillow | 12.3.0 | MIT-CMU | dev |
| pluggy | 1.6.0 | MIT License | dev |
| pycparser | 3.0 | BSD-3-Clause | runtime |
| pydantic | 2.13.5 | MIT | runtime |
| pydantic-settings | 2.15.0 | MIT | runtime |
| pydantic_core | 2.46.5 | MIT | runtime |
| Pygments | 2.21.0 | BSD-2-Clause | dev |
| PyOTP | 2.10.0 | MIT | runtime |
| pytest | 8.4.2 | MIT License | dev |
| pytest-asyncio | 0.26.0 | Apache-2.0 | dev |
| python-dotenv | 1.2.3 | BSD-3-Clause | runtime |
| PyYAML | 6.0.3 | MIT License | runtime |
| qrcode | 8.2 | BSD License | runtime |
| referencing | 0.37.0 | MIT | runtime |
| rpds-py | 2026.6.3 | MIT | runtime |
| ruff | 0.16.8 | MIT | dev |
| SQLAlchemy | 2.0.54 | MIT | runtime |
| starlette | 1.6.0 | BSD-3-Clause | runtime |
| types-qrcode | 8.2.0.20260518 | Apache-2.0 | dev |
| typing-inspection | 0.4.4 | MIT | runtime |
| typing_extensions | 4.16.0 | PSF-2.0 | runtime |
| tzdata | 2026.4 | Apache-2.0 | runtime |
| uvicorn | 0.53.0 | BSD-3-Clause | runtime |
| watchfiles | 1.2.0 | MIT License | runtime |
| websockets | 17.1 | BSD-3-Clause | runtime |

## npm (miniapp)

| Пакет | Лицензия | Сборка |
|---|---|---|
| @asamuzakjp/css-color@7.0.0 | MIT | разработка |
| @asamuzakjp/dom-selector@9.1.4 | MIT | разработка |
| @babel/code-frame@7.29.7 | MIT | разработка |
| @babel/helper-validator-identifier@7.29.7 | MIT | разработка |
| @babel/runtime@7.29.7 | MIT | разработка |
| @bramus/specificity@2.4.2 | MIT | разработка |
| @csstools/color-helpers@6.1.1 | MIT-0 | разработка |
| @csstools/css-calc@3.4.0 | MIT | разработка |
| @csstools/css-color-parser@4.2.3 | MIT | разработка |
| @csstools/css-parser-algorithms@4.0.0 | MIT | разработка |
| @csstools/css-syntax-patches-for-csstree@1.1.14 | MIT-0 | разработка |
| @csstools/css-tokenizer@4.0.0 | MIT | разработка |
| @exodus/bytes@1.15.1 | MIT | разработка |
| @jridgewell/resolve-uri@3.1.2 | MIT | разработка |
| @jridgewell/sourcemap-codec@1.6.0 | MIT | разработка |
| @jridgewell/trace-mapping@0.3.31 | MIT | разработка |
| @maxhub/max-ui@0.5.0 | MIT | прод |
| @oxc-project/types@0.150.0 | MIT | разработка |
| @playwright/test@1.63.0 | Apache-2.0 | разработка |
| @radix-ui/react-compose-refs@1.1.5 | MIT | прод |
| @radix-ui/react-slot@1.3.3 | MIT | прод |
| @redocly/ajv@8.11.2 | MIT | разработка |
| @redocly/config@0.22.0 | MIT | разработка |
| @redocly/openapi-core@1.34.20 | MIT | разработка |
| @rolldown/binding-win32-x64-msvc@1.2.9 | MIT | разработка |
| @rolldown/pluginutils@1.0.1 | MIT | разработка |
| @testing-library/dom@10.4.1 | MIT | разработка |
| @testing-library/react@16.3.3 | MIT | разработка |
| @testing-library/user-event@14.6.7 | MIT | разработка |
| @types/aria-query@5.0.4 | MIT | разработка |
| @types/chai@5.2.3 | MIT | разработка |
| @types/deep-eql@4.0.2 | MIT | разработка |
| @types/estree@1.0.9 | MIT | разработка |
| @types/react-dom@19.2.3 | MIT | разработка |
| @types/react@19.2.17 | MIT | прод |
| @vitejs/plugin-react@6.1.1 | MIT | разработка |
| @vitest/mocker@5.0.1 | MIT | разработка |
| @vitest/spy@5.0.1 | MIT | разработка |
| agent-base@7.1.4 | MIT | разработка |
| ansi-colors@4.1.3 | MIT | разработка |
| ansi-regex@5.0.1 | MIT | разработка |
| ansi-styles@5.2.0 | MIT | разработка |
| argparse@2.0.1 | Python-2.0 | разработка |
| aria-query@5.3.0 | Apache-2.0 | разработка |
| assertion-error@2.0.1 | MIT | разработка |
| axe-core@4.13.0 | MPL-2.0 | разработка |
| balanced-match@1.0.2 | MIT | разработка |
| bidi-js@1.1.0 | MIT | разработка |
| brace-expansion@2.1.7 | MIT | разработка |
| chai@6.2.2 | MIT | разработка |
| change-case@5.4.4 | MIT | разработка |
| colorette@1.4.0 | MIT | разработка |
| css-tree@3.2.1 | MIT | разработка |
| csstype@3.2.3 | MIT | прод |
| data-urls@7.0.0 | MIT | разработка |
| debug@4.4.3 | MIT | разработка |
| decimal.js@10.6.0 | MIT | разработка |
| dequal@2.0.3 | MIT | разработка |
| detect-libc@2.1.2 | Apache-2.0 | разработка |
| dom-accessibility-api@0.5.16 | MIT | разработка |
| entities@8.1.0 | BSD-2-Clause | разработка |
| es-module-lexer@2.3.2 | MIT | разработка |
| estree-walker@3.0.3 | MIT | разработка |
| expect-type@1.4.0 | Apache-2.0 | разработка |
| fast-deep-equal@3.1.3 | MIT | разработка |
| fdir@6.5.0 | MIT | разработка |
| html-encoding-sniffer@6.0.0 | MIT | разработка |
| https-proxy-agent@7.0.6 | MIT | разработка |
| index-to-position@1.2.0 | MIT | разработка |
| is-potential-custom-element-name@1.0.1 | MIT | разработка |
| js-levenshtein@1.1.6 | MIT | разработка |
| js-tokens@4.0.0 | MIT | разработка |
| js-yaml@4.3.2 | MIT | разработка |
| jsdom@30.1.0 | MIT | разработка |
| json-schema-traverse@1.0.0 | MIT | разработка |
| lightningcss-win32-x64-msvc@1.33.0 | MPL-2.0 | разработка |
| lightningcss@1.33.0 | MPL-2.0 | разработка |
| lru-cache@11.5.2 | BlueOak-1.0.0 | разработка |
| lz-string@1.5.0 | MIT | разработка |
| magic-string@1.4.1 | MIT | разработка |
| mdn-data@2.27.1 | CC0-1.0 | разработка |
| minimatch@5.1.9 | ISC | разработка |
| ms@2.1.3 | MIT | разработка |
| nanoid@3.3.19 | MIT | разработка |
| obug@2.2.1 | MIT | разработка |
| openapi-typescript@7.13.0 | MIT | разработка |
| parse-json@8.3.0 | MIT | разработка |
| parse5@8.0.1 | MIT | разработка |
| picocolors@1.1.1 | ISC | разработка |
| picomatch@4.0.7 | MIT | разработка |
| playwright-core@1.63.0 | Apache-2.0 | разработка |
| playwright@1.63.0 | Apache-2.0 | разработка |
| pluralize@8.0.0 | MIT | разработка |
| postcss@8.5.28 | MIT | разработка |
| pretty-format@27.5.1 | MIT | разработка |
| punycode@2.3.1 | MIT | разработка |
| react-dom@19.2.8 | MIT | прод |
| react-is@17.0.2 | MIT | разработка |
| react@19.2.8 | MIT | прод |
| require-from-string@2.0.2 | MIT | разработка |
| rolldown@1.2.9 | MIT | разработка |
| saxes@6.0.0 | ISC | разработка |
| scheduler@0.27.0 | MIT | прод |
| siginfo@2.0.0 | ISC | разработка |
| source-map-js@1.2.1 | BSD-3-Clause | разработка |
| stackback@0.0.2 | MIT | разработка |
| std-env@4.2.0 | MIT | разработка |
| supports-color@10.2.2 | MIT | разработка |
| tinybench@6.1.4 | MIT | разработка |
| tinyexec@1.3.0 | MIT | разработка |
| tinyglobby@0.2.17 | MIT | разработка |
| tldts-core@7.4.13 | MIT | разработка |
| tldts@7.4.13 | MIT | разработка |
| tough-cookie@6.0.2 | BSD-3-Clause | разработка |
| tr46@6.0.0 | MIT | разработка |
| type-fest@4.41.0 | (MIT OR CC0-1.0) | разработка |
| typescript@5.9.3 | Apache-2.0 | разработка |
| undici@8.10.2 | MIT | разработка |
| uri-js-replace@1.0.1 | MIT | разработка |
| vite@8.3.0 | MIT | разработка |
| vitest@5.0.1 | MIT | разработка |
| w3c-xmlserializer@5.0.0 | MIT | разработка |
| webidl-conversions@8.0.1 | BSD-2-Clause | разработка |
| whatwg-mimetype@5.0.0 | MIT | разработка |
| whatwg-url@16.0.1 | MIT | разработка |
| whatwg-url@17.1.1 | MIT | разработка |
| why-is-node-running@2.3.0 | MIT | разработка |
| xml-name-validator@5.0.0 | Apache-2.0 | разработка |
| xmlchars@2.2.0 | MIT | разработка |
| yaml-ast-parser@0.0.43 | Apache-2.0 | разработка |
| yargs-parser@21.1.1 | ISC | разработка |
