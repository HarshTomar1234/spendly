from database.db import get_db


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


def get_recent_transactions(user_id, limit=10):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT amount, category, date, description"
            " FROM expenses"
            " WHERE user_id = ?"
            " ORDER BY date DESC"
            " LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [
            {
                "date": row["date"],
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"],
            }
            for row in rows
        ]
    finally:
        db.close()


def get_summary_stats(user_id):
    db = get_db()
    row1 = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total_spent,"
        "       COUNT(*)                  AS transaction_count"
        " FROM  expenses"
        " WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    row2 = db.execute(
        "SELECT   category, SUM(amount) AS cat_total"
        " FROM    expenses"
        " WHERE   user_id = ?"
        " GROUP BY category"
        " ORDER BY cat_total DESC"
        " LIMIT   1",
        (user_id,),
    ).fetchone()
    db.close()
    return {
        "total_spent":       float(row1["total_spent"]),
        "transaction_count": int(row1["transaction_count"]),
        "top_category":      row2["category"] if row2 else "—",
    }


def get_category_breakdown(user_id):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT category, SUM(amount) AS total"
            " FROM expenses"
            " WHERE user_id = ?"
            " GROUP BY category"
            " ORDER BY total DESC",
            (user_id,)
        ).fetchall()
    finally:
        db.close()

    if not rows:
        return []

    grand_total = sum(row["total"] for row in rows)

    result = [
        {"name": row["category"], "amount": row["total"], "pct": round(row["total"] / grand_total * 100)}
        for row in rows
    ]

    remainder = 100 - sum(item["pct"] for item in result)
    result[0]["pct"] += remainder

    return result
