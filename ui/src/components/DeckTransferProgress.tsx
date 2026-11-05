import type { NativeDeckJob } from '../deckManagerApi';

/** `showDetail={false}` where a heading above already says what is running (Deck Manager's banner). */
export function DeckTransferProgress({ detail, progress, showDetail = true }: Pick<NativeDeckJob, 'detail' | 'progress'> & { showDetail?: boolean }) {
  const total = progress?.total;
  const completed = Math.max(0, Math.min(progress?.completed ?? 0, total ?? Infinity));
  return <div className="deck-transfer-progress" role="status" aria-label={showDetail ? undefined : detail}>
    {showDetail ? <span>{detail}</span> : null}
    <progress aria-label="Deck transfer progress" max={total && total > 0 ? total : 1}
      value={total && total > 0 ? completed : undefined} />
    {total && total > 0 ? <small>{Math.floor(completed / total * 100)}%</small> : null}
  </div>;
}
