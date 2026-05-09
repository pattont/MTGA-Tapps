select
  g.id as game_id,
  g.started_at,
  g.outcome,
  p.opening_hand_size,
  p.mulligans,
  group_concat(h.display_name, ' | ') as opening_hand
from games g
join participants p on p.game_id = g.id and p.role = 'player'
left join game_opening_hand_cards h on h.participant_id = p.id
where p.deck_name is null or p.deck_name = ''
group by g.id
order by g.started_at desc;
