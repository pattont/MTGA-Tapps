import { formatPercent } from '../dashboardData';

interface WinRateBarProps {
  wins: number;
  losses: number;
  winRate: number | null;
}

export function WinRateBar({ wins, losses, winRate }: WinRateBarProps) {
  const decided = wins + losses;
  if (decided === 0 || winRate === null || winRate === undefined) {
    return <span className="win-rate-value">—</span>;
  }
  const winShare = (100 * wins) / decided;
  return (
    <div className="win-rate-cell" title={`${wins}W – ${losses}L`}>
      <span className="win-rate-value">{formatPercent(winRate)}</span>
      <span className="win-rate-track" aria-hidden="true">
        <span className="win-rate-fill" style={{ width: `${winShare}%` }} />
      </span>
    </div>
  );
}
