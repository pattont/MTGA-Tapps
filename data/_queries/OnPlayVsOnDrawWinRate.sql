select
  case p.went_first
    when 1 then 'on the play'
    when 0 then 'on the draw'
    else 'unknown'
  end as play_draw,
  count(*) as games,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  sum(g.outcome = 'draw') as draws,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate
from games g
join participants p on p.game_id = g.id and p.role = 'player'
group by p.went_first
order by play_draw;
