-- Star (WatchEvent) records for ONE extraction chunk.
-- Placeholders {start_suffix} / {end_suffix} are YYMMDD strings filled in by fakestars/data/extract_bigquery.py.
-- Only the needed columns are selected (BigQuery bills by column), and date + type are filtered first.
SELECT
  id            AS event_id,
  type,
  actor.id      AS actor_id,
  actor.login   AS actor_login,
  repo.id       AS repo_id,
  repo.name     AS repo_name,
  created_at
FROM `githubarchive.day.20*`
WHERE _TABLE_SUFFIX BETWEEN '{start_suffix}' AND '{end_suffix}'
  AND type = 'WatchEvent'
