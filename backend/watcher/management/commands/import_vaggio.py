"""Import a Vaggio SQLite database: ``manage.py import_vaggio path/to/vaggio.sqlite3``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from watcher.services.vaggio_import import VaggioImportError, import_vaggio


class Command(BaseCommand):
    help = "Import jobs, applications, interactions, cover letters and profile from Vaggio."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path", help="Path to the Vaggio vaggio.sqlite3 file.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            counts = import_vaggio(Path(options["path"]))
        except VaggioImportError as error:
            raise CommandError(str(error)) from error
        for name, value in counts.as_dict().items():
            self.stdout.write(f"{name}: {value}")
