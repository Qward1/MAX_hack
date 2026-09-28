import { MaxUI } from '@maxhub/max-ui';
import '@maxhub/max-ui/dist/styles.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { useTheme } from '../shared/theme';
import '../shared/styles/main.css';
import '../shared/styles/system.css';

/** MAX UI следует теме, выбранной на устройстве; без выбора — теме MAX и системы. */
function Resident() {
  const { chosen } = useTheme();
  return (
    <MaxUI colorScheme={chosen ?? undefined}>
      <App />
    </MaxUI>
  );
}

/** Мини-приложение жителя внутри MAX (прежняя точка входа). */
export function renderMiniApp(root: HTMLElement) {
  createRoot(root).render(
    <StrictMode>
      <Resident />
    </StrictMode>,
  );
}
