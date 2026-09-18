import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DomSignalApi, IncidentDetail } from '../shared/api/client';
import { App } from './App';

const house = {
  id: '00000000-0000-0000-0000-000000000101',
  name: 'Демо-дом',
  address: 'Тестовая улица, 1',
  role: 'resident' as const,
  is_demo: true,
};

function clientWith(items: IncidentDetail[] = []): DomSignalApi {
  return {
    capabilities: vi.fn().mockResolvedValue({
      contract_version: 'c0.1',
      environment: 'test',
      features: {
        test_auth: true,
        report_create: true,
        incident_board: true,
        incident_detail: true,
        max_live: false,
        group_mode: false,
        miniapp: true,
        photo_analysis: false,
        voice: false,
        admin: false,
        routes: false,
        appeals: false,
        reminders: false,
        media: false,
      },
    }),
    authenticate: vi.fn().mockResolvedValue(undefined),
    me: vi.fn().mockResolvedValue({ id: 'user', display_name: 'Житель', houses: [house] }),
    incidents: vi.fn().mockResolvedValue({
      items,
      page: { limit: 50, offset: 0, total: items.length },
    }),
    incident: vi.fn().mockImplementation(async (id: string) => items.find((item) => item.id === id)),
    createReport: vi.fn(),
    workStatus: vi.fn().mockResolvedValue({ ticket_id: null }),
    observe: vi.fn(),
  };
}

describe('house board', () => {
  it('renders a real empty state after loading API data', async () => {
    render(<App client={clientWith()} />);
    expect(screen.getByText('Загрузка доски дома')).toBeTruthy();
    expect(await screen.findByText('На доске пока пусто')).toBeTruthy();
  });

  it('allows retry after an API error', async () => {
    const client = clientWith();
    vi.mocked(client.capabilities)
      .mockRejectedValueOnce(new Error('Сеть недоступна'))
      .mockResolvedValueOnce(await clientWith().capabilities());
    render(<App client={client} />);
    expect(await screen.findByText('Доска временно недоступна')).toBeTruthy();
    fireEvent.click(screen.getByText('Попробовать снова'));
    await waitFor(() => expect(screen.getByText('На доске пока пусто')).toBeTruthy());
  });
});
