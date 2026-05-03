-- Replace the value in the params CTE with a game id from RecentGames.sql.
with params(game_id) as (
  values ('PASTE_GAME_ID_HERE')
)
select
  e.elapsed_seconds,
  printf('%d:%02d', e.elapsed_seconds / 60, e.elapsed_seconds % 60) as elapsed,
  e.turn_number,
  e.actor_role,
  e.event_type,
  e.event_subtype,
  e.text,
  e.player_life,
  e.opponent_life
from game_events e
join params p on p.game_id = e.game_id
order by e.event_time, e.id;
