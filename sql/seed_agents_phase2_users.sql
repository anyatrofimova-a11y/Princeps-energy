-- seed_agents_phase2_users.sql
-- Seeds a single operator account + weekly-report opt-in so the
-- ReportAgent has a cohort of 1 to run against until full auth is wired.
-- Idempotent — uses ON CONFLICT so re-running is safe.

INSERT INTO users (user_id, email, name)
VALUES (
    gen_random_uuid(),
    'anya.trofimova@yahoo.com',
    'Anya Trofimova'
)
ON CONFLICT (email) DO NOTHING;

INSERT INTO user_preferences (user_id, weekly_report_enabled, slack_dm_enabled, timezone)
SELECT user_id, true, true, 'Europe/London'
  FROM users
 WHERE email = 'anya.trofimova@yahoo.com'
ON CONFLICT (user_id) DO UPDATE SET
    weekly_report_enabled = EXCLUDED.weekly_report_enabled,
    slack_dm_enabled      = EXCLUDED.slack_dm_enabled,
    timezone              = EXCLUDED.timezone,
    updated_at            = now();
