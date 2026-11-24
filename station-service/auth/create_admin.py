"""Bootstrap the first administrator after applying the identity migration."""

from getpass import GetPassWarning, getpass
import warnings

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import database_url
from .db import engine_for
from .models import User
from .security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, normalize_email, password_hasher


def main() -> None:
    with Session(engine_for(database_url())) as db:
        if db.scalar(select(User.id).where(User.role == "admin").limit(1)) is not None:
            raise SystemExit("An administrator already exists.")

    try:
        email = normalize_email(validate_email(input("Admin email: ").strip(), check_deliverability=False).normalized)
    except EmailNotValidError as error:
        raise SystemExit(str(error)) from None
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
    with Session(engine_for(database_url())) as db:
        if db.scalar(select(User.id).where(User.role == "admin").limit(1)) is not None:
            raise SystemExit("An administrator already exists.")
        db.add(User(email=email, password_hash=hashed, role="admin"))
        try:
            db.commit()
        except IntegrityError:
            raise SystemExit("An account already exists for this email.") from None
    print(f"Administrator created for {email}.")


if __name__ == "__main__":
    main()
