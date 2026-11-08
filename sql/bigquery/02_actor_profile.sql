-- Activity profile (all event types) for every account that starred something in the window.
-- Events are deduplicated by event id before counting.
WITH ev AS (
  SELECT id, ANY_VALUE(type) AS type, ANY_VALUE(actor.id) AS actor_id, ANY_VALUE(created_at) AS created_at
  FROM `githubarchive.day.20*`
  WHERE _TABLE_SUFFIX BETWEEN '{start_suffix}' AND '{end_suffix}'
  GROUP BY id
),
stargazers AS (
  SELECT DISTINCT actor_id FROM ev WHERE type = 'WatchEvent'
)
SELECT
  actor_id,
  COUNT(*)                                                           AS n_events,
  COUNTIF(type = 'WatchEvent')                                       AS n_watch,
  COUNTIF(type = 'PushEvent')                                        AS n_push,
  COUNTIF(type = 'ForkEvent')                                        AS n_fork,
  COUNTIF(type = 'CreateEvent')                                      AS n_create,
  COUNTIF(type = 'IssuesEvent')                                      AS n_issues,
  COUNTIF(type IN ('PullRequestEvent', 'PullRequestReviewEvent',
                   'PullRequestReviewCommentEvent', 'PullRequestReviewThreadEvent')) AS n_pr,
  COUNTIF(type IN ('IssueCommentEvent', 'CommitCommentEvent'))       AS n_comment,
  MIN(created_at)                                                    AS first_ts,
  MAX(created_at)                                                    AS last_ts
FROM ev
JOIN stargazers USING (actor_id)
GROUP BY actor_id
