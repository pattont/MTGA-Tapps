-- Visible player draws by card. Starts filling for games played after drawn-card capture was added.
select
  d.display_name,
  coalesce(d.type_category, 'Other') as type_category,
  count(*) as times_drawn,
  count(distinct d.game_id) as games_seen,
  round(100.0 * count(distinct d.game_id) / nullif((select count(*) from games), 0), 1) as pct_of_games
from game_drawn_cards d
join participants p on p.id = d.participant_id and p.role = 'player'
group by d.display_name, d.type_category
order by times_drawn desc, d.display_name;
