-- Replace Llanowar Elves with the target card name.
with seen as (
  select h.game_id, h.participant_id, h.display_name, 'opening' as source
  from game_opening_hand_cards h
  union all
  select d.game_id, d.participant_id, d.display_name, 'draw' as source
  from game_drawn_cards d
)
select
  g.started_at,
  coalesce(p.deck_name, 'Unknown') as deck_name,
  g.outcome,
  sum(case when seen.source = 'opening' then 1 else 0 end) as opening_copies,
  sum(case when seen.source = 'draw' then 1 else 0 end) as drawn_copies,
  count(*) as total_seen
from seen
join games g on g.id = seen.game_id
join participants p on p.id = seen.participant_id and p.role = 'player'
where replace(seen.display_name, ' (Creature 1/1)', '') = 'Llanowar Elves'
group by g.id
order by coalesce(g.started_at, g.ended_at) desc;
