#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Couldn't import Django. Is it installed and is your virtualenv active? "
            "Try `uv sync` then `uv run hub/manage.py ...`."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
