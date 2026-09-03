"""Attach every ledger entry to the release it paid for.

Written by hand rather than generated. `makemigrations` cannot add a
non-nullable foreign key without being told what to backfill existing rows
with, and for this column there is no defensible answer: an epsilon spend whose
release is unknown is precisely the unaccounted disclosure the constraint
exists to forbid. Inventing a default would create the corrupt state rather
than prevent it.

So the column is added nullable and then tightened. On an empty table -- which
is every environment, because no release path existed before this migration --
both steps are trivial. If some environment does hold entries, the AlterField
fails loudly and a human decides what those spends paid for. That is the
correct failure mode: refusing to guess beats a plausible wrong answer.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0001_initial"),
        ("benchmarks", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="ledgerentry",
            name="release",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ledger_entries",
                to="benchmarks.benchmarkrelease",
            ),
        ),
        migrations.AlterField(
            model_name="ledgerentry",
            name="release",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ledger_entries",
                to="benchmarks.benchmarkrelease",
            ),
        ),
    ]
