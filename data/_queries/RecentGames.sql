select
  g.started_at,
  g.ended_at,
  round(g.duration_seconds / 60.0, 1) as duration_minutes,
  g.total_turns,
  g.outcome,
  g.outcome_reason,
  coalesce(p.deck_name, '(unknown)') as deck_name,
  p.deck_id,
  p.opening_hand_size,
  p.mulligans,
  p.ending_life as your_ending_life,
  opp.ending_life as opponent_ending_life
from games g
join participants p on p.game_id = g.id and p.role = 'player'
left join participants opp on opp.game_id = g.id and opp.role = 'opponent'
order by g.started_at desc
limit 50;
