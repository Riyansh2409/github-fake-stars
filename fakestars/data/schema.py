"""Column names and the set of GH Archive event types we accept."""

# Raw per-event schema written by the GH Archive downloader and the synthetic generator.
RAW_COLUMNS = ["event_id", "type", "actor_id", "actor_login", "repo_id", "repo_name", "created_at"]

# Public GitHub event types recorded by GH Archive (2015+ schema).
KNOWN_EVENT_TYPES = [
    "WatchEvent", "ForkEvent", "PushEvent", "CreateEvent", "DeleteEvent", "IssuesEvent",
    "IssueCommentEvent", "PullRequestEvent", "PullRequestReviewEvent",
    "PullRequestReviewCommentEvent", "PullRequestReviewThreadEvent", "CommitCommentEvent",
    "ReleaseEvent", "PublicEvent", "MemberEvent", "GollumEvent", "SponsorshipEvent",
    "DiscussionEvent",
]

STAR = "WatchEvent"  # a "star" is recorded as WatchEvent(action=started)

# Event-type groups for the per-account activity profile.
PROFILE_GROUPS = {
    "n_push": ["PushEvent"],
    "n_fork": ["ForkEvent"],
    "n_create": ["CreateEvent"],
    "n_issues": ["IssuesEvent"],
    "n_pr": ["PullRequestEvent", "PullRequestReviewEvent", "PullRequestReviewCommentEvent",
             "PullRequestReviewThreadEvent"],
    "n_comment": ["IssueCommentEvent", "CommitCommentEvent"],
}
PROFILE_COLUMNS = ["actor_id", "n_events", "n_watch", *PROFILE_GROUPS, "first_ts", "last_ts"]
