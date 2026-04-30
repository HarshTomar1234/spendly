# Spec: Login and Logout

## Overview
Implement session-based login and logout so registered users can authenticate into Spendly. This step upgrades the existing stub `GET /login` into a full form that accepts a POST, validates credentials against the `users` table, and stores the authenticated user's id and name in Flask's `session`. The `GET /logout` stub is also implemented — it clears the session and redirects to the landing page. Together these two routes form the authentication boundary that all future protected pages will rely on.

## Depends on
- Step 01 — Database setup (`users` table, `get_db()`)
- Step 02 — Registration (`create_user()`, `users` rows exist to authenticate against)

## Routes
- `GET /login` — render login form — public (already exists as stub, upgrade it)
- `POST /login` — validate credentials, set session, redirect to `/` — public
- `GET /logout` — clear session, redirect to `/` — logged-in (stub upgrade)

## Database changes
No new tables or columns.

One new DB helper must be added to `database/db.py`:
- `get_user_by_email(email)` — queries the `users` table for a row matching the given email; returns a `sqlite3.Row` (or `None` if not found). Caller is responsible for password verification.

## Templates
- **Modify**: `templates/login.html`
  - Add `action="{{ url_for('login') }}"` and `method="post"` to the form tag
  - Add `name="email"` and `name="password"` attributes to the inputs
  - Display flash messages (errors and success notices) from the session
  - Keep all existing visual design
- **Modify**: `templates/base.html`
  - Navbar shows "Sign in" + "Get started" when logged out
  - Navbar shows "Sign out" only when `session["user_id"]` is set — "Get started" is hidden

## Files to change
- `app.py` — upgrade `login()` to handle `GET` and `POST`; implement `logout()` with session clear and redirect; import `session` from Flask and `check_password_hash` from werkzeug
- `database/db.py` — add `get_user_by_email(email)` helper
- `templates/login.html` — wire up form action/method and flash message display
- `templates/base.html` — conditional navbar based on session state

## Files to create
None.

## New dependencies
No new dependencies. Uses Flask's built-in `session`, `flash`, `redirect`, `url_for`, and `werkzeug.security.check_password_hash` (already installed).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never use f-strings in SQL
- Verify passwords with `werkzeug.security.check_password_hash` — never compare plaintext
- Store only `user_id` (int) and `user_name` (str) in `session` — never store the password hash
- On login failure, re-render the form with a generic error ("Invalid email or password.") — do not distinguish between wrong email and wrong password (prevents user enumeration)
- On login success, `flash` a welcome message and `redirect` to `url_for('landing')`
- `logout()` must call `session.clear()` then redirect to `url_for('landing')`
- `GET /login` and `GET /register` must redirect to `/` if `session["user_id"]` is already set — logged-in users must not be able to access auth pages
- Use `abort(405)` if an unsupported HTTP method reaches a route
- All templates extend `base.html`
- Use CSS variables — never hardcode hex values
- Use `url_for()` for every internal link — never hardcode URLs

## Definition of done
- [ ] `GET /login` renders the login form with email and password fields
- [ ] Submitting the form with valid credentials (e.g. `demo@spendly.com` / `demo123`) sets `session["user_id"]` and redirects to `/`
- [ ] Submitting with a wrong password shows `"Invalid email or password."` flash and stays on the login page
- [ ] Submitting with an unregistered email shows the same generic error flash
- [ ] `GET /logout` clears the session and redirects to `/`
- [ ] After logout, `session["user_id"]` is no longer present
- [ ] The `/logout` route no longer returns the raw stub string
- [ ] Visiting `/login` while logged in redirects to `/` instead of showing the form
- [ ] Visiting `/register` while logged in redirects to `/` instead of showing the form
- [ ] Navbar shows "Sign out" (linking to `/logout`) when logged in — "Sign in" and "Get started" are hidden
- [ ] Navbar shows "Sign in" and "Get started" when logged out — "Sign out" is hidden
- [ ] Session stores `user_id` and `user_name` — never the password hash
