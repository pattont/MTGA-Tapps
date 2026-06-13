-- Recent games: opening hand + known player draws, with observed land rate.
select
  g.started_at,
  coalesce(p.deck_name, 'Unknown') as deck_name,
  g.outcome,
  count(seen.display_name) as cards_seen,
  sum(case when seen.type_category = 'Land' or seen.display_name like '%(Land)' then 1 else 0 end) as lands_seen,
  round(
    100.0 * sum(case when seen.type_category = 'Land' or seen.display_name like '%(Land)' then 1 else 0 end)
      / nullif(count(seen.display_name), 0),
    1
  ) as land_seen_pct,
  sum(case when seen.source = 'opening' then 1 else 0 end) as opening_cards,
  sum(case when seen.source = 'draw' then 1 else 0 end) as known_draws
from games g
join participants p on p.game_id = g.id and p.role = 'player'
left join (
  select game_id, participant_id, display_name, type_category, 'opening' as source
  from game_opening_hand_cards
  union all
  select game_id, participant_id, display_name, type_category, 'draw' as source
  from game_drawn_cards
) seen on seen.game_id = g.id and seen.participant_id = p.id
group by g.id
order by coalesce(g.started_at, g.ended_at) desc
limit 50;
