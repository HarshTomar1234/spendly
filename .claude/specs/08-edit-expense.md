# Spec: Edit Expense

## Overview
Step 8 lets a logged-in user edit an existing expense through a pre-filled form at
`/expenses/<id>/edit`. The route already exists as a GET stub returning a plain string;
this step upgrades it to a full GET + POST handler. On GET the form is pre-populated
with the current expense values; on POST the validated changes are written back to the
`expenses` row. Two new query helpers (`get_expense_by_id`, `update_expense`) are added
to `database/queries.py`. The profile page's transaction list is updated to expose each
row's `id` so edit links can be rendered.

## Depends on
- Step 1: Database setup (`expenses` table exists)
- Step 3: Login / Logout (`session["user_id"]` is available)
- Step 4 / 5: Profile page renders the transaction list that will carry edit links
- Step 7: Add Expense (defines `CATEGORIES`, `add_expense.html` pattern to follow)

## Routes
- `GET /expenses/<int:id>/edit` — render pre-filled edit form — logged-in only
- `POST /expenses/<int:id>/edit` — validate and persist the update — logged-in only

## Database changes
No new tables or columns. All required columns (`id`, `user_id`, `amount`, `category`,
`date`, `description`) already exist on the `expenses` table.

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`
  - Form with `method="POST"` and `action` pointing to `url_for("edit_expense", id=expense.id)`
  - Fields pre-filled from the fetched expense row:
    - `amount` — number input, `step="0.01"`, `min="0.01"`, required
    - `category` — `<select>` with the 7 fixed options; current category selected
    - `date` — `<input type="date">`, required, pre-filled with current date
    - `description` — text input, optional, max 200 chars, pre-filled
  - Submit button ("Save Changes") and a cancel link back to `/profile`
  - Display inline error message when validation fails, retaining the last submitted values

- **Modify:** `templates/profile.html`
  - Add an "Edit" link/button to each row in the recent transactions table, pointing to
    `url_for("edit_expense", id=transaction.id)`
  - Requires that `id` is now present in each transaction dict (see Files to change)

## Files to change
- `database/queries.py`
  - Add `get_expense_by_id(expense_id, user_id)` — returns the expense row as a dict if
    it belongs to `user_id`, otherwise `None`
  - Add `update_expense(expense_id, user_id, amount, category, expense_date, description)`
    — updates `amount`, `category`, `date`, `description` WHERE `id = ? AND user_id = ?`
  - Update `get_recent_transactions` to also `SELECT id` so the profile page can render
    edit links

- `app.py`
  - Replace the stub `edit_expense` route with a GET + POST handler:
    - Both methods: redirect to `/login` if not authenticated
    - GET: call `get_expense_by_id`; `abort(404)` if not found; render `edit_expense.html`
    - POST: read form, validate identically to `add_expense` POST, call `update_expense`,
      flash "Expense updated!", redirect to `url_for("profile")`
  - Import `get_expense_by_id` and `update_expense` from `database.queries`

- `templates/profile.html`
  - Add "Edit" links in the transactions table (each row now has `transaction.id`)

## Files to create
- `templates/edit_expense.html` — the pre-filled edit form

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Foreign keys PRAGMA is already enabled in `get_db()`; do not bypass it
- Ownership check is mandatory: the `WHERE id = ? AND user_id = ?` clause in both
  `get_expense_by_id` and `update_expense` prevents editing another user's expense
- Unauthenticated GET and POST to `/expenses/<id>/edit` must redirect to `/login`
- If `get_expense_by_id` returns `None`, call `abort(404)` — do not return a bare string
- Validation rules for POST (identical to add_expense):
  - `amount`: required, positive number > 0 (parse with `float()`; catch `ValueError`)
  - `category`: required, must be one of the 7 fixed categories
  - `date`: required, valid `YYYY-MM-DD` (parse with `datetime.strptime`)
  - `description`: optional; strip whitespace; store `None` if blank
  - On validation error, re-render `edit_expense.html` with the error and the last-submitted
    values (not the original DB values)
- After a successful update, flash "Expense updated!" and redirect to `url_for("profile")`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- No inline `<style>` tags
- Currency must display as ₹ — never £ or $
- Use `url_for()` for every internal link — never hardcode URLs

## Definition of done
- [ ] Visiting `/expenses/<id>/edit` while logged out redirects to `/login`
- [ ] Visiting `/expenses/<id>/edit` for a non-existent or another user's expense returns 404
- [ ] Visiting `/expenses/<id>/edit` while logged in shows a form pre-filled with the current values
- [ ] The category dropdown shows the current category as the selected option
- [ ] Submitting valid changes redirects to `/profile` and the updated values appear in the transaction list
- [ ] Submitting with a missing or zero amount re-renders the form with an error and the last-entered values retained
- [ ] Submitting with an invalid category re-renders the form with an error
- [ ] Submitting with an invalid date re-renders the form with an error
- [ ] Submitting without a description saves with `description = NULL` (no error)
- [ ] Each row in the profile transaction table has a working "Edit" link
