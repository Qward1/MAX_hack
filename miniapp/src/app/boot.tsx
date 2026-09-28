import { MaxUI } from '@maxhub/max-ui';
import '@maxhub/max-ui/dist/styles.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import '../shared/styles/main.css';
import '../shared/styles/system.css';

/** Мини-приложение жителя внутри MAX (прежняя точка входа). */
export function renderMiniApp(root: HTMLElement) {
  createRoot(root).render(
    <StrictMode>
      <MaxUI>
        <App />
      </MaxUI>
    </StrictMode>,
  );
}
