"""Enforce the frozen domain vocabulary (docs/GLOSSARY.md).

The domain nouns were changed once, in Sprint 1, when migrations were still
throwaway. They are frozen now. This test fails the build if the retired names
reappear in the hub's domain layer, because a half-renamed codebase is worse
than either name consistently applied -- and the rename already caused one real
runtime break (the agent could not parse an ack whose field had been renamed).

Demo *data* is exempt: seeded contributors are called "Plant 01" and their data
directories are `plant-01/`, because the worked example is deliberately
industrial. What is banned is the retired names as *identifiers* -- classes,
fields, imports, query lookups.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parent

# Retired identifier -> replacement. Matched as whole words in Python source.
RETIRED = {
    r"\bPlant\b": "Contributor",
    r"\bSector\b": "Cohort",
    r"\bplant__": "contributor__",
    r"\bsector__": "cohort__",
    r"\bplants\.models\b": "contributors.models",
    r"\bPlantTokenAuthentication\b": "ContributorTokenAuthentication",
    r"\bplant_position\b": "contributor_position",
}

# Files whose *content* is legitimately industrial demo data.
EXEMPT_FILES = {
    "seed_demo.py",  # seeds contributors literally named "Plant 01"
    "test_naming_drift.py",  # this file names the banned terms on purpose
}


def _python_sources() -> list[Path]:
    return [
        path
        for path in HUB_DIR.rglob("*.py")
        if "migrations" not in path.parts
        and "__pycache__" not in path.parts
        and path.name not in EXEMPT_FILES
    ]


def _strip_demo_strings(source: str) -> str:
    """Remove quoted literals so demo names like "Plant 01" don't trip the check.

    Crude but sufficient: we are looking for identifiers, and identifiers never
    live inside string literals in the code we are policing.
    """
    source = re.sub(r'"""(?:.|\n)*?"""', "", source)
    source = re.sub(r"'''(?:.|\n)*?'''", "", source)
    source = re.sub(r'"[^"\n]*"', '""', source)
    source = re.sub(r"'[^'\n]*'", "''", source)
    return source


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: str(p.relative_to(HUB_DIR)))
def test_no_retired_domain_nouns(path: Path) -> None:
    code = _strip_demo_strings(path.read_text(encoding="utf-8"))

    offences = [
        f"{pattern.strip(chr(92) + 'b')} -> use {replacement}"
        for pattern, replacement in RETIRED.items()
        if re.search(pattern, code)
    ]

    assert not offences, (
        f"{path.relative_to(HUB_DIR)} uses retired domain vocabulary: "
        + "; ".join(offences)
        + ". See docs/GLOSSARY.md -- the domain nouns are frozen."
    )


def test_glossary_exists_and_lists_the_frozen_nouns() -> None:
    """The glossary is the reference this test enforces; it must not go missing."""
    glossary = HUB_DIR.parent / "docs" / "GLOSSARY.md"
    assert glossary.exists(), "docs/GLOSSARY.md is missing."

    text = glossary.read_text(encoding="utf-8")
    for noun in ("Collaboration", "Cohort", "Contributor", "MetricDefinition",
                 "ReportingPeriod", "Submission"):
        assert noun in text, f"GLOSSARY.md does not define {noun}."
