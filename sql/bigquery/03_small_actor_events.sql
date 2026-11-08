-- Non-star events of stargazers that have at most {max_other} non-star events in the window.
-- These few rows are all the low-activity rule needs ("at most one extra event, on the starred
-- repository, on the same day"), so the rule itself is evaluated locally in Python.
WITH ev AS (
  SELECT id, ANY_VALUE(type) AS type, ANY_VALUE(actor.id) AS actor_id,
         ANY_VALUE(repo.id) AS repo_id, ANY_VALUE(created_at) AS created_at
  FROM `githubarchive.day.20*`
  WHERE _TABLE_SUFFIX BETWEEN '{start_suffix}' AND '{end_suffix}'
  GROUP BY id
),
stargazers AS (
  SELECT DISTINCT actor_id FROM ev WHERE type = 'WatchEvent'
),
other_counts AS (
  SELECT actor_id, COUNT(*) AS n_other
  FROM ev JOIN stargazers USING (actor_id)
  WHERE type != 'WatchEvent'
  GROUP BY actor_id
)
SELECT ev.id AS event_id, actor_id, ev.repo_id, ev.type, ev.created_at
FROM ev JOIN other_counts USING (actor_id)
WHERE other_counts.n_other <= {max_other}
  AND ev.type != 'WatchEvent'
