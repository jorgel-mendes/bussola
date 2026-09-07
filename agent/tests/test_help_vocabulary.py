"""The vocabulary a contributor actually reads (S3-10).

`hub/test_naming_drift.py` polices IDENTIFIERS, and does so by stripping every
docstring and string literal before it looks — deliberately, because demo data
is legitimately called "Plant 01". The consequence is that user-facing prose was
never in its scope at all, and that is exactly where the drift was found:

    $ bussola-agent --help
    submit    Compute this plant's aggregate for one metric and period...
    position  Show where this plant sits against its cohort's published...

Typer renders command docstrings and option help as the CLI's front page, so
those two lines were the first thing a new contributor read. The hub had been
saying "contributor" since Sprint 1; the agent was still saying "plant".

WHY IT IS WRONG RATHER THAN JUST INCONSISTENT. The agent is the generic half of
the product — the thing a hospital, a lab or a statistical agency installs. Only
the *seeded demo* is cement plants. Hard-coding the worked example into the tool
tells every non-industrial contributor that the product was not built for them.

This test asserts against the RENDERED help rather than the source, so it checks
what a user sees rather than what the code looks like.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from bussola_agent.cli import app

runner = CliRunner()

#: Retired noun -> the frozen replacement (docs/GLOSSARY.md).
RETIRED = {r"\bplants?\b": "contributor", r"\bsectors?\b": "cohort"}

COMMANDS = [[], ["submit"], ["position"], ["check"]]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a) or "root")
def test_cli_help_uses_the_frozen_vocabulary(argv):
    """No retired noun anywhere a contributor can read it."""
    result = runner.invoke(app, [*argv, "--help"])
    assert result.exit_code == 0

    text = result.stdout
    offences = [
        f"{pattern.strip(chr(92) + 'b')} -> use {replacement}"
        for pattern, replacement in RETIRED.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]

    assert not offences, (
        f"`bussola-agent {' '.join(argv) or ''} --help` uses retired vocabulary: "
        + "; ".join(offences)
        + ". The domain nouns are frozen (docs/GLOSSARY.md), and CLI help is the "
        "first thing a contributor reads."
    )


def test_the_help_still_says_what_the_commands_do():
    """Guards against fixing the vocabulary by deleting the sentence.

    A blank help line would pass the check above and be worse than the drift.
    """
    result = runner.invoke(app, ["--help"])

    assert "contributor" in result.stdout
    assert "position" in result.stdout and "submit" in result.stdout
