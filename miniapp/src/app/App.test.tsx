import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DomSignalApi, IncidentDetail } from '../shared/api/client';
import { apiWith } from '../test/fixtures';
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
    ...apiWith(items),
    notificationLaunch: vi.fn(),
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
    expect(screen.getByText('Загружаем проблемы дома')).toBeTruthy();
    expect(await screen.findByText('О проблемах пока не сообщали')).toBeTruthy();
    // Пустое состояние говорит, что здесь появится и что сделать.
    expect(screen.getByText(/Здесь появятся проблемы, о которых сообщили соседи/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Сообщить о проблеме' })).toBeTruthy();
  });

  it('allows retry after an API error', async () => {
    const client = clientWith();
    vi.mocked(client.capabilities)
      .mockRejectedValueOnce(new Error('Сеть недоступна'))
      .mockResolvedValueOnce(await clientWith().capabilities());
    render(<App client={client} />);
    expect(await screen.findByText('Не удалось загрузить проблемы дома')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.getByText('О проблемах пока не сообщали')).toBeTruthy());
  });
});

describe('no house yet (D1)', () => {
  const open = {
    id: '00000000-0000-0000-0000-000000000301',
    name: 'Открытый дом',
    address: 'Казань, Открытая улица, 3',
    joined: false,
  };

  function houseless(openHouses: unknown = []): DomSignalApi {
    const client = clientWith();
    vi.mocked(client.me).mockResolvedValue({ id: 'user', display_name: 'Гость', houses: [] } as never);
    vi.mocked(client.openHouses).mockImplementation(async () => {
      if (openHouses instanceof Error) throw openHouses;
      return openHouses as never;
    });
    return client;
  }

  it('explains how to get into the house from the chat without a dead end', async () => {
    render(<App client={houseless()} />);
    expect(await screen.findByText('Откройте ДомСигнал кнопкой из вашего домового чата.')).toBeTruthy();
    expect(screen.queryByText('Выберите дом')).toBeNull();
    expect(screen.getByRole('button', { name: 'Проверить снова' })).toBeTruthy();
  });

  it('lists open houses and joins one, then shows its board', async () => {
    const client = houseless([open]);
    vi.mocked(client.joinOpenHouse).mockResolvedValue({ ...open, joined: true });
    render(<App client={client} />);
    const join = await screen.findByRole('button', { name: `Выбрать дом: ${open.address}` });
    vi.mocked(client.me).mockResolvedValue({
      id: 'user',
      display_name: 'Гость',
      houses: [{ id: open.id, name: open.name, address: open.address, role: 'resident', is_demo: false }],
    } as never);
    fireEvent.click(join);
    await waitFor(() => expect(client.joinOpenHouse).toHaveBeenCalledWith(open.id));
    expect(await screen.findByText(open.address)).toBeTruthy();
    expect(await screen.findByText('О проблемах пока не сообщали')).toBeTruthy();
  });

  it('says in plain words when the house can no longer be chosen', async () => {
    const client = houseless([open]);
    const { error } = await import('../test/fixtures');
    vi.mocked(client.joinOpenHouse).mockRejectedValue(error(404));
    render(<App client={client} />);
    fireEvent.click(await screen.findByRole('button', { name: `Выбрать дом: ${open.address}` }));
    expect(await screen.findByText('Этот дом больше нельзя выбрать. Обновите список.')).toBeTruthy();
    expect(screen.queryByText('PRIVATE')).toBeNull();
  });

  it('keeps the chat path visible when the open house list fails', async () => {
    render(<App client={houseless(new Error('offline'))} />);
    expect(await screen.findByText('Не удалось загрузить список домов')).toBeTruthy();
    expect(screen.getByText('Откройте ДомСигнал кнопкой из вашего домового чата.')).toBeTruthy();
  });

  it('never resolves a chat button reference as a notification launch', async () => {
    window.history.replaceState(null, '', `/?test_start_param=c_${'a'.repeat(32)}`);
    const client = houseless();
    render(<App client={client} />);
    expect(await screen.findByText('Откройте ДомСигнал кнопкой из вашего домового чата.')).toBeTruthy();
    expect(client.notificationLaunch).not.toHaveBeenCalled();
    window.history.replaceState(null, '', '/');
  });

  it('explains a lost house access instead of a generic failure', async () => {
    window.history.replaceState(null, '', `/?house=${house.id}`);
    render(<App client={houseless()} />);
    expect(await screen.findByText('Нет доступа к этому дому')).toBeTruthy();
    expect(
      screen.getByText(/Откройте ДомСигнал кнопкой из вашего домового чата или выберите другой дом/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'К выбору дома' }));
    expect(await screen.findByText('Откройте ДомСигнал кнопкой из вашего домового чата.')).toBeTruthy();
    window.history.replaceState(null, '', '/');
  });
});
