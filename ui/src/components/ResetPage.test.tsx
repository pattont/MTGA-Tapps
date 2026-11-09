import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ResetPage } from './ResetPage';

function stubReset(response: Response) {
  const fetchMock = vi.fn(async () => response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function openAndConfirm() {
  fireEvent.click(screen.getByRole('button', { name: 'Reset tracker data…' }));
  const dialog = screen.getByRole('dialog', { name: 'Reset tracker data?' });
  const confirm = within(dialog).getByRole('button', { name: 'Reset tracker data' });
  expect(confirm).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText(/to confirm/), { target: { value: 'reset' } });
  expect(confirm).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText(/to confirm/), { target: { value: 'RESET' } });
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);
}

describe('ResetPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('says what is deleted and what stays before anything happens', () => {
    const fetchMock = stubReset(new Response('{}'));
    render(<ResetPage />);
    const deleted = screen.getByRole('heading', { name: 'What gets deleted' }).parentElement!;
    expect(within(deleted).getByText(/Turn timings and game replays/)).toBeInTheDocument();
    const kept = screen.getByRole('heading', { name: 'What stays' }).parentElement!;
    expect(within(kept).getByText(/Deck Manager's saved decks/)).toBeInTheDocument();
    expect(within(kept).getByText(/A reset never touches Arena/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Settings → Backup & restore' })).toHaveAttribute(
      'href',
      '#/settings',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('resets only after RESET is typed, then shows where the copy went', async () => {
    const fetchMock = stubReset(
      new Response(JSON.stringify({ ok: true, backup: '/data/tracker.sqlite3.backup.1.pre-reset' })),
    );
    render(<ResetPage />);
    openAndConfirm();
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Reset done. Your stats start from zero.',
    );
    expect(screen.getByText('/data/tracker.sqlite3.backup.1.pre-reset')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/db/reset', expect.objectContaining({ method: 'POST' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('explains a refusal during a game without the HTTP code', async () => {
    stubReset(new Response('A game is in progress. Reset after it ends.', { status: 409 }));
    render(<ResetPage />);
    openAndConfirm();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /^A game is in progress\. Reset after it ends\.$/,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('asks for Arena to be closed first', async () => {
    stubReset(new Response('Close MTG Arena before you reset.', { status: 409 }));
    render(<ResetPage />);
    expect(screen.getByText(/Close MTG Arena first/)).toBeInTheDocument();
    openAndConfirm();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /^Close MTG Arena before you reset\.$/,
    );
  });
});
