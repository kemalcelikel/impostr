"""Cookie names and lifetimes shared by auth and its request dependencies."""

SESSION_COOKIE_NAME = "impostr_session"
CSRF_COOKIE_NAME = "impostr_csrf"
SESSION_TTL_SECONDS = 12 * 60 * 60
PREAUTH_CSRF_TTL_SECONDS = 10 * 60
