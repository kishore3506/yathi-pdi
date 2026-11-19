import getpass
import re
import sys
from datetime import datetime

from argon2 import PasswordHasher

try:
    from .database import get_db, init_db
except ImportError:
    from database import get_db, init_db


def main():
    init_db()
    email = input("Administrator email: ").strip().lower()
    display_name = input("Administrator name: ").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise SystemExit("Enter a valid email address.")
    if not display_name:
        raise SystemExit("Administrator name is required.")

    password = getpass.getpass("Administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        raise SystemExit("Use a password with at least 12 characters.")
    if password != confirmation:
        raise SystemExit("The passwords did not match.")

    conn = get_db()
    try:
        if conn.execute(
            "SELECT 1 FROM users WHERE role = 'administrator' AND is_active = 1 LIMIT 1"
        ).fetchone():
            raise SystemExit("An active administrator already exists; no account was changed.")
        now = datetime.utcnow().isoformat()
        conn.execute(
            """
            INSERT INTO users (email, display_name, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, 'administrator', ?, ?)
            """,
            (email, display_name, PasswordHasher().hash(password), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"Administrator account created for {email}.")


if __name__ == "__main__":
    main()
