select
  s.id as session_id,
  s.started_at,
  s.ended_at,
  s.games_played,
  s.wins,
  s.losses,
  s.runtime_seconds as play_time_seconds,
  printf('%d:%02d:%02d', s.runtime_seconds / 3600, (s.runtime_seconds % 3600) / 60, s.runtime_seconds % 60) as play_time,
  round(s.runtime_seconds / 60.0 / nullif(s.games_played, 0), 1) as avg_minutes_per_game
from tracker_sessions s
order by s.started_at desc;
