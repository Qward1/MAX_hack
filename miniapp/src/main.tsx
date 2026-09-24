import { chooseSurface } from './site/entry';

const root = document.getElementById('root');
if (!root) throw new Error('Root element is missing');

// SITE-ENTRY-2026-09-26: внутри MAX (есть подписанные initData) корень — мини-
// приложение, как раньше; в обычном браузере — публичная страница продукта.
// Тестовые стенды с тестовым входом по-прежнему открывают мини-приложение.
void chooseSurface(() => window.WebApp?.initData ?? '', (input, init) => fetch(input, init)).then(async (surface) => {
  if (surface === 'miniapp') (await import('./app/boot')).renderMiniApp(root);
  else (await import('./site/boot')).renderLanding(root);
});
