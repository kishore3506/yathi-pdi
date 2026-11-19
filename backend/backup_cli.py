import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    from .services.portable_backup import create_backup, import_backup
    from .settings import BACKUP_DIR
except ImportError:
    from services.portable_backup import create_backup, import_backup
    from settings import BACKUP_DIR


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create or restore a PDI business-data backup.")
    commands = parser.add_subparsers(dest="command", required=True)

    backup_parser = commands.add_parser("backup", help="Create a consistent ZIP backup.")
    backup_parser.add_argument("--destination", type=Path)

    restore_parser = commands.add_parser(
        "restore-initial",
        help="Import a backup into a newly initialized app with no business records.",
    )
    restore_parser.add_argument("archive", type=Path)

    args = parser.parse_args(argv)
    if args.command == "backup":
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        destination = args.destination or (
            BACKUP_DIR
            / f"yathi-pdi-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
        )
        print(create_backup(destination))
        return 0

    result = import_backup(args.archive)
    print(f"Restore complete: {result['imported_files']} files imported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
