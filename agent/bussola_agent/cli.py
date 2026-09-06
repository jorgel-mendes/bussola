"""bussola-agent command line interface.

Exit codes are meaningful, because this runs unattended from cron:

* 0 — submitted (or would submit, under --dry-run)
* 1 — configuration or local data problem; operator must intervene
* 2 — hub rejected the data (422); do not retry unchanged
* 3 — transient problem (network, 409, 5xx); a later retry may succeed
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from bussola_agent.client import HubClient, HubError, PositionUnavailable
from bussola_agent.compute import ComputationError, check_bounds, load_records, local_mean
from bussola_agent.config import AGENT_VERSION, AgentConfig, ConfigError
from bussola_contracts import SubmissionPayload

app = typer.Typer(
    add_completion=False,
    help="Compute a local aggregate and submit it to the Bussola hub.",
)

EXIT_LOCAL_ERROR = 1
EXIT_REJECTED = 2
EXIT_RETRYABLE = 3


@app.command()
def submit(
    metric: Annotated[str, typer.Option(help="Metric code, e.g. energy_per_tonne.")],
    period: Annotated[str, typer.Option(help="Reporting period label, e.g. 2026-07.")],
    file: Annotated[Path, typer.Option(help="CSV file holding this plant's records.")],
    column: Annotated[str, typer.Option(help="Column to aggregate.")] = "value",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Compute and show what would be sent, but send nothing."),
    ] = False,
) -> None:
    """Compute this plant's aggregate for one metric and period, and submit it."""
    try:
        config = AgentConfig.from_env()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(EXIT_LOCAL_ERROR) from exc

    try:
        with HubClient(config) as client:
            spec = client.fetch_metric(metric)

            series = load_records(file, column, period=period)
            value = local_mean(series)
            check_bounds(value, spec)

            payload = SubmissionPayload(
                metric_code=metric,
                period_label=period,
                value=value,
                n_records=series.len(),
                agent_version=AGENT_VERSION,
            )

            typer.echo(f"contributor: {config.contributor_label}")
            typer.echo(f"metric     : {spec.code} ({spec.unit})")
            typer.echo(f"period     : {period}")
            typer.echo(f"records    : {payload.n_records}")
            typer.echo(f"value      : {payload.value} {spec.unit}")

            if dry_run:
                # The operator sees exactly what would leave the plant, before
                # anything does. Trust in this system is built here.
                typer.secho("\nDRY RUN — nothing was sent.", fg=typer.colors.YELLOW)
                raise typer.Exit(0)

            ack = client.submit(payload)

    except ComputationError as exc:
        typer.secho(f"\nLocal data problem:\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(EXIT_LOCAL_ERROR) from exc
    except HubError as exc:
        colour = typer.colors.YELLOW if exc.retryable else typer.colors.RED
        typer.secho(f"\n{exc}", fg=colour, err=True)
        raise typer.Exit(EXIT_RETRYABLE if exc.retryable else EXIT_REJECTED) from exc

    action = "Submitted" if ack.created else "Updated existing submission"
    typer.secho(f"\n{action} (id={ack.id}) for {ack.contributor}.", fg=typer.colors.GREEN)


@app.command()
def position(
    metric: Annotated[str, typer.Option(help="Metric code, e.g. energy_per_tonne.")],
    period: Annotated[str, typer.Option(help="Reporting period label, e.g. 2026-07.")],
) -> None:
    """Show where this plant sits against its cohort's published benchmark.

    This is the question a member actually joined to have answered, and it is
    asked from the plant's own machine with the plant's own credential. It reads
    an already-published differentially private release; it spends no privacy
    budget and releases nothing, so it is safe to run on a schedule.
    """
    try:
        config = AgentConfig.from_env()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(EXIT_LOCAL_ERROR) from exc

    try:
        with HubClient(config) as client:
            report = client.fetch_position(metric=metric, period=period)
    except PositionUnavailable as exc:
        # Not an error in the usual sense: for most of a reporting period,
        # "the operator has not released this yet" is simply the state of the
        # world. Yellow, and a retryable exit code, so a cron log does not fill
        # up with red for a system that is working correctly.
        colour = typer.colors.YELLOW if exc.retryable else typer.colors.RED
        typer.secho(f"\nNo position available:\n{exc}", fg=colour, err=True)
        raise typer.Exit(EXIT_RETRYABLE if exc.retryable else EXIT_LOCAL_ERROR) from exc
    except HubError as exc:
        colour = typer.colors.YELLOW if exc.retryable else typer.colors.RED
        typer.secho(f"\n{exc}", fg=colour, err=True)
        raise typer.Exit(EXIT_RETRYABLE if exc.retryable else EXIT_REJECTED) from exc

    typer.echo(f"contributor : {config.contributor_label}")
    typer.echo(f"cohort      : {report.cohort_code}")
    typer.echo(f"metric      : {report.metric_code} ({report.metric_unit})")
    typer.echo(f"period      : {report.period_label}")
    typer.echo("")
    typer.echo(f"your value  : {report.your_value} {report.metric_unit}")
    typer.echo(
        f"benchmark   : q25={report.released_q25}  "
        f"median={report.released_median}  q75={report.released_q75}"
    )
    typer.echo(f"              from {report.n_contributors} contributors, ε={report.epsilon_spent}")
    typer.echo("")

    if report.is_usable:
        typer.secho(f"You are in {report.quartile}.", fg=typer.colors.GREEN, bold=True)
    else:
        # The Sprint 2 finding, surfaced to the member who is affected by it.
        typer.secho("Your position cannot be reported.", fg=typer.colors.YELLOW, bold=True)

    if report.caveat:
        typer.secho(f"\n{report.caveat}", fg=typer.colors.YELLOW)


@app.command()
def check() -> None:
    """Verify configuration and hub reachability without submitting anything."""
    try:
        config = AgentConfig.from_env()
    except ConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(EXIT_LOCAL_ERROR) from exc

    typer.echo(f"hub        : {config.hub_url}")
    typer.echo(f"contributor: {config.contributor_label}")
    typer.echo(f"token      : …{config.token[-4:]}")

    try:
        with HubClient(config) as client:
            response = client._client.get(
                f"{config.hub_url}/api/v1/metrics/", headers=client._headers
            )
            client._raise_for_status(response)
            codes = [item["code"] for item in response.json()]
    except HubError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(EXIT_RETRYABLE if exc.retryable else EXIT_REJECTED) from exc

    typer.secho(f"\nOK — hub reachable, {len(codes)} metric(s): {', '.join(codes)}",
                fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
