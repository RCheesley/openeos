import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('todos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='todo',
            name='recurrence',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'Does not repeat'),
                    ('weekly', 'Weekly'),
                    ('biweekly', 'Every two weeks'),
                    ('monthly', 'Monthly'),
                    ('quarterly', 'Quarterly'),
                ],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='todo',
            name='recurrence_day',
            field=models.PositiveSmallIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='todo',
            name='previous_occurrence',
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='next_occurrence',
                to='todos.todo',
            ),
        ),
    ]
