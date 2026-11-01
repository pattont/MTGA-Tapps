import { Badge } from './Badge';
import { drawStatusOf, LAND_STREAK_HINT, type DrawStatusFlags } from '../drawStatus';

/** The Draw Status table cell: a badge, or plain "Normal". */
export function DrawStatusBadge({ row }: { row: DrawStatusFlags }) {
  const status = drawStatusOf(row);
  if (status === 'flood') {
    return <Badge tone="flood">Flood</Badge>;
  }
  if (status === 'screw') {
    return <Badge tone="screw">Mana Screw</Badge>;
  }
  if (status === 'streak') {
    return (
      <Badge tone="streak" title={LAND_STREAK_HINT}>
        Land streak
      </Badge>
    );
  }
  return <>Normal</>;
}
