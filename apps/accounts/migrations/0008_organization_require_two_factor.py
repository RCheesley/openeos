from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_organization_invitation'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='require_two_factor',
            field=models.BooleanField(
                default=False,
                help_text='Anyone who has not set up two-factor authentication is asked to do so '
                          'the next time they open a page in this organisation.',
                verbose_name='Require two-step sign-in for everyone in this organisation',
            ),
        ),
    ]
