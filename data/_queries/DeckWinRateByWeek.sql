select
  strftime('%Y-%W', g.started_at) as year_week,
  coalesce(p.deck_name, '(unknown)') as deck_name,
  count(*) as games,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate
from games g
join participants p on p.game_id = g.id and p.role = 'player'
group by year_week, p.deck_name
order by year_week desc, games desc;
