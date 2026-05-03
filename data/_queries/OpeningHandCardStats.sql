select
  coalesce(p.deck_name, '(unknown)') as deck_name,
  h.display_name as card_name,
  count(*) as opening_hands_seen,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate_when_seen
from game_opening_hand_cards h
join games g on g.id = h.game_id
join participants p on p.id = h.participant_id and p.role = 'player'
group by p.deck_name, h.display_name
order by opening_hands_seen desc, win_rate_when_seen desc, card_name;
