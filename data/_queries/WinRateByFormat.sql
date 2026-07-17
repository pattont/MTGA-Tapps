select
  coalesce(m.format, '(unknown)') as raw_format,
  coalesce(m.queue, '(unknown)') as queue,
  count(*) as games,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  sum(g.outcome = 'draw') as draws,
  sum(g.outcome not in ('win', 'loss', 'draw')) as unknown_results,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate,
  round(avg(g.duration_seconds) / 60.0, 1) as avg_game_minutes
from games g
join matches m on m.id = g.match_id
group by m.format, m.queue
order by games desc, win_rate desc;
