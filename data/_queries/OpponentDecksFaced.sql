select
  coalesce(p.deck_name, '(unknown)') as your_deck,
  coalesce(opp.deck_archetype, opp.deck_name, '(unknown)') as opponent_deck,
  count(*) as games,
  sum(g.outcome = 'win') as wins,
  sum(g.outcome = 'loss') as losses,
  round(100.0 * sum(g.outcome = 'win') / nullif(sum(g.outcome in ('win', 'loss')), 0), 1) as win_rate
from games g
join participants p on p.game_id = g.id and p.role = 'player'
left join participants opp on opp.game_id = g.id and opp.role = 'opponent'
group by p.deck_name, opponent_deck
order by games desc, your_deck, opponent_deck;
