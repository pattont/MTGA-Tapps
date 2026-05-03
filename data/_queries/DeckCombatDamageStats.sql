select
  coalesce(p.deck_name, '(unknown)') as deck_name,
  count(*) as games,
  sum(s.damage_dealt) as total_damage_dealt,
  round(avg(s.damage_dealt), 1) as avg_damage_dealt,
  sum(s.damage_taken) as total_damage_taken,
  round(avg(s.damage_taken), 1) as avg_damage_taken,
  sum(s.life_gained) as total_life_gained,
  sum(s.cards_drawn) as total_cards_drawn,
  sum(s.cards_discarded) as total_cards_discarded,
  sum(s.cards_milled) as total_cards_milled
from game_participant_stats s
join games g on g.id = s.game_id
join participants p on p.id = s.participant_id and p.role = 'player'
group by p.deck_name
order by games desc;
