select
  'FORMAT_QUEUE_MISMATCH' as finding,
  m.id as row_id,
  m.format as current_value,
  m.queue as queue,
  m.event_name as event_name
from matches m
where coalesce(m.queue, '') <> ''
  and coalesce(m.event_name, '') <> ''
  and m.queue = m.event_name
  and m.format <> m.queue
union all
select
  'TURN_COUNT_MISMATCH' as finding,
  g.id as row_id,
  cast(g.total_turns as text) as current_value,
  cast(g.player_turns as text) as queue,
  cast(g.opponent_turns as text) as event_name
from games g
where g.total_turns is not null
  and g.player_turns is not null
  and g.opponent_turns is not null
  and g.total_turns <> g.player_turns + g.opponent_turns
union all
select
  'MISSING_DECK_NAME' as finding,
  p.id as row_id,
  p.deck_id as current_value,
  p.game_id as queue,
  null as event_name
from participants p
where p.role = 'player'
  and coalesce(p.deck_id, '') <> ''
  and coalesce(p.deck_name, '') = ''
order by finding, row_id;
