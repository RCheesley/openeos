from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scorecards', '0002_cadences_and_entry_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='scorecardmetric',
            name='warning_value',
            field=models.DecimalField(blank=True, decimal_places=4, help_text='Optional. A value that misses the goal but is no worse than this is shown as a warning instead of off track.', max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='scorecardentry',
            name='in_warning',
            field=models.BooleanField(default=False),
        ),
    ]
