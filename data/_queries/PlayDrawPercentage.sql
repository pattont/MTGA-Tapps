select
  count(*) as games_played,
  sum(p.went_first = 1) as games_on_the_play,
  round(100.0 * sum(p.went_first = 1) / nullif(count(*), 0), 1) as percentage_on_the_play,
  sum(p.went_first = 0) as games_on_the_draw,
  round(100.0 * sum(p.went_first = 0) / nullif(count(*), 0), 1) as percentage_on_the_draw
from games g
join participants p on p.game_id = g.id and p.role = 'player'
where p.went_first in (0, 1);
