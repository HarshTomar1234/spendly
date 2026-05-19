from database.db import get_db


def _build_date_clause(date_from, date_to):
    if date_from and date_to:
        return " AND date BETWEEN ? AND ?", [date_from, date_to]
    return "", []


def get_user_by_id(user_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "name": row["name"],
            "email": row["email"],
            "member_since": row["created_at"],
        }
    finally:
        db.close()


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    db = get_db()
    date_clause, date_params = _build_date_clause(date_from, date_to)
    try:
        rows = db.execute(
            "SELECT id, amount, category, date, description"
            " FROM expenses"
            " WHERE user_id = ?" + date_clause +
            " ORDER BY date DESC"
            " LIMIT ?",
            [user_id] + date_params + [limit]
        ).fetchall()
        return [
            {
                "id":          row["id"],
                "date":        row["date"],
                "description": row["description"] or "",
                "category":    row["category"],
                "amount":      round(float(row["amount"]), 2),
            }
            for row in rows
        ]
    finally:
        db.close()


def get_summary_stats(user_id, date_from=None, date_to=None):
    db = get_db()
    date_clause, date_params = _build_date_clause(date_from, date_to)
    try:
        row1 = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total_spent,"
            "       COUNT(*)                  AS transaction_count"
            " FROM  expenses"
            " WHERE user_id = ?" + date_clause,
            [user_id] + date_params,
        ).fetchone()
        row2 = db.execute(
            "SELECT   category, SUM(amount) AS cat_total"
            " FROM    expenses"
            " WHERE   user_id = ?" + date_clause +
            " GROUP BY category"
            " ORDER BY cat_total DESC"
            " LIMIT   1",
            [user_id] + date_params,
        ).fetchone()
        return {
            "total_spent":       round(float(row1["total_spent"]), 2),
            "transaction_count": int(row1["transaction_count"]),
            "top_category":      row2["category"] if row2 else "—",
        }
    finally:
        db.close()


def get_category_breakdown(user_id, date_from=None, date_to=None):
    db = get_db()
    date_clause, date_params = _build_date_clause(date_from, date_to)
    try:
        rows = db.execute(
            "SELECT category, SUM(amount) AS total"
            " FROM expenses"
            " WHERE user_id = ?" + date_clause +
            " GROUP BY category"
            " ORDER BY total DESC",
            [user_id] + date_params
        ).fetchall()
    finally:
        db.close()

    if not rows:
        return []

    grand_total = sum(row["total"] for row in rows)

    result = [
        {"name": row["category"], "amount": round(float(row["total"]), 2), "pct": round(row["total"] / grand_total * 100)}
        for row in rows
    ]

    remainder = 100 - sum(item["pct"] for item in result)
    result[0]["pct"] += remainder

    return result


def get_expense_by_id(expense_id, user_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, amount, category, date, description FROM expenses"
            " WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id":          row["id"],
            "amount":      row["amount"],
            "category":    row["category"],
            "date":        row["date"],
            "description": row["description"] or "",
        }
    finally:
        db.close()


def update_expense(expense_id, user_id, amount, category, expense_date, description):
    db = get_db()
    try:
        cur = db.execute(
            "UPDATE expenses SET amount=?, category=?, date=?, description=?"
            " WHERE id=? AND user_id=?",
            (amount, category, expense_date, description, expense_id, user_id),
        )
        db.commit()
        return cur.rowcount
    finally:
        db.close()


def remove_expense(expense_id, user_id):
    db = get_db()
    try:
        db.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        db.commit()
    finally:
        db.close()


def insert_expense(user_id, amount, category, expense_date, description):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description),
        )
        db.commit()
    finally:
        db.close()
