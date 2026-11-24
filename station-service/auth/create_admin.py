"""Bootstrap the first administrator in this machine's configured identity database."""

from getpass import GetPassWarning, getpass
import warnings

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import database_description
from .db import engine, missing_schema
from .models import User
from .security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, normalize_email, password_hasher


def _existing_admin(db: Session) -> str | None:
    return db.scalar(select(User.email).where(User.role == "admin").order_by(User.created_at).limit(1))


def _refuse_existing_admin(email: str) -> None:
    raise SystemExit(
        f"An administrator already exists in this database ({email}). No account was created. "
        "Run python -m auth.list_users to see accounts; invite residents from the station interface."
    )


def main() -> None:
    print(f"Identity database: {database_description()}")
    problem = missing_schema()
    if problem is not None:
        raise SystemExit(problem)
    with Session(engine()) as db:
        if (admin := _existing_admin(db)) is not None:
            _refuse_existing_admin(admin)

    try:
        email = normalize_email(validate_email(input("Admin email: ").strip(), check_deliverability=False).normalized)
    except EmailNotValidError as error:
        raise SystemExit(str(error)) from None
    with Session(engine()) as db:
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            raise SystemExit(f"An account already exists for {email}. No account was created.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            password = getpass("Admin password: ")
            confirmation = getpass("Confirm password: ")
        except GetPassWarning:
            raise SystemExit("Use an interactive terminal that can hide password input.") from None
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise SystemExit(f"Use {MIN_PASSWORD_LENGTH}–{MAX_PASSWORD_LENGTH} characters for the password.")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    hashed = password_hasher.hash(password)
    with Session(engine()) as db:
        if (admin := _existing_admin(db)) is not None:
            _refuse_existing_admin(admin)
        db.add(User(email=email, password_hash=hashed, role="admin"))
        try:
            db.commit()
        except IntegrityError:
            raise SystemExit(f"An account already exists for {email}. No account was created.") from None
    print(f"Administrator created for {email}.")


if __name__ == "__main__":
    main()
