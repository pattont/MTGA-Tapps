select
  coalesce(p.deck_name, '(unknown)') as deck_name,
  p.deck_id,
  count(*) as games,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  sum(g.outcome not in ('win', 'loss')) as unknown_results,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate,
  round(avg(g.duration_seconds) / 60.0, 1) as avg_game_minutes
from games g
join participants p on p.game_id = g.id and p.role = 'player'
group by p.deck_name, p.deck_id
order by games desc, win_rate desc;
