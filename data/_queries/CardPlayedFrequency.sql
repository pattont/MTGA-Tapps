select
  coalesce(p.deck_name, '(unknown)') as deck_name,
  c.display_name as card_name,
  c.type_category,
  sum(c.played_count) as times_played,
  count(distinct c.game_id) as games_played_in,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate_when_played
from game_card_summary c
join games g on g.id = c.game_id
join participants p on p.id = c.participant_id and p.role = 'player'
where c.played_count > 0
group by p.deck_name, c.display_name, c.type_category
order by times_played desc, games_played_in desc, card_name;
