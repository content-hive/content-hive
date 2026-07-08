"""Content Hive command-line interface."""

import argparse
import getpass
import sys

from contenthive.services.user import user_service


def _prompt_password() -> str:
    """Prompt for a new password twice and return it when both entries match."""
    password = getpass.getpass("New password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise ValueError("Passwords do not match")
    return password


def _cmd_admin_reset_password(args: argparse.Namespace) -> None:
    """Reset an admin user's password."""
    password = args.password or _prompt_password()
    user_service.reset_admin_password(args.username, password)
    print(f"Admin password reset for user: {args.username}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contenthive", description="Content Hive administration CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    admin_parser = subparsers.add_parser("admin", help="Admin user management")
    admin_subparsers = admin_parser.add_subparsers(dest="admin_command", required=True)

    reset_parser = admin_subparsers.add_parser(
        "reset-password",
        help="Reset an admin user's password",
    )
    reset_parser.add_argument("--username", required=True, help="Admin username")
    reset_parser.add_argument(
        "--password",
        help="New password (prompts interactively if omitted)",
    )
    reset_parser.set_defaults(handler=_cmd_admin_reset_password)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
