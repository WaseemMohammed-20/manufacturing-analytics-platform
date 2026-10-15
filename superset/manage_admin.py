import argparse
import getpass
import os
import sys

from superset import app


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or safely create a Superset administrator.")
    parser.add_argument("action", choices=("check", "create"))
    parser.add_argument("--username", default=os.environ.get("SUPERSET_ADMIN_USERNAME", "admin"))
    parser.add_argument("--email", default=os.environ.get("SUPERSET_ADMIN_EMAIL", "admin@example.com"))
    arguments = parser.parse_args()

    with app.app_context():
        security = app.appbuilder.sm
        user = security.find_user(username=arguments.username)
        if user is not None:
            is_admin = any(role.name == "Admin" for role in user.roles)
            status = "administrator" if is_admin else "exists but is not an administrator"
            print(f"{arguments.username}: {status}")
            if arguments.action == "create" and not is_admin:
                print("Refusing to change an existing account's role or password; choose another username.")
                return 2
            return 0 if is_admin else 1

        if arguments.action == "check":
            print(f"{arguments.username}: not found")
            return 1

        password = getpass.getpass("New Superset administrator password (16+ characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if len(password) < 16:
            print("Password must be at least 16 characters.", file=sys.stderr)
            return 2
        if password != confirmation:
            print("Passwords did not match.", file=sys.stderr)
            return 2
        role = security.find_role("Admin")
        if role is None:
            print("Superset Admin role is missing; run superset init first.", file=sys.stderr)
            return 2
        user = security.add_user(
            username=arguments.username,
            first_name="Local",
            last_name="Administrator",
            email=arguments.email,
            role=role,
            password=password,
        )
        if user is None:
            print("Superset did not create the account.", file=sys.stderr)
            return 2
        print(f"Created Superset administrator: {arguments.username}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())