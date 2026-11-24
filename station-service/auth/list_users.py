"""List accounts in the configured identity database without exposing secrets.

Selects only email, role, active state, and creation time; password hashes, invitation
tokens, and session tokens are never loaded.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import database_description
from .db import engine, missing_schema
from .models import User


def main() -> None:
    print(f"Identity database: {database_description()}")
    problem = missing_schema()
    if problem is not None:
        raise SystemExit(problem)
    with Session(engine()) as db:
        rows = db.execute(
            select(User.email, User.role, User.is_active, User.created_at).order_by(User.created_at, User.email)
        ).all()
    if not rows:
        print("No accounts. Create the first administrator with: python -m auth.create_admin")
        return
    width = max(len("EMAIL"), *(len(row.email) for row in rows))
    print(f"{'EMAIL':<{width}}  {'ROLE':<8}  {'STATUS':<8}  CREATED (UTC)")
    for row in rows:
        status = "active" if row.is_active else "inactive"
        created = row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "-"
        print(f"{row.email:<{width}}  {row.role:<8}  {status:<8}  {created}")
    print(f"{len(rows)} account(s).")


if __name__ == "__main__":
    main()
