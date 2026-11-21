"""Every event the application writes to the audit log, with a plain description.

Names are dotted and lower-case: the thing that changed, then what happened to
it. The descriptions are shown on the organisation's audit page next to the
name; ``{rock}``-style placeholders are filled in with the organisation's own
vocabulary. The README lists the same names, and a test keeps the two in step.
"""

EVENTS = {
    # Signing in and the user's own account
    'user.login': 'Signed in',
    'user.logout': 'Signed out',
    'user.login_failed': 'Failed sign-in',
    'user.password_changed': 'Password changed',
    'user.password_reset': 'Password set from an emailed link',
    'user.email_changed': 'Email address changed',
    'user.two_factor_enabled': 'Two-factor authentication enabled',
    'user.two_factor_disabled': 'Two-factor authentication disabled',
    'user.backup_codes_regenerated': 'Two-factor backup codes regenerated',
    # Members
    'user.invited': 'User invited',
    'member.role_changed': 'Member role changed',
    'member.records_reassigned': 'Member records handed over',
    'member.removed': 'Member removed',
    # Teams
    'team.created': 'Team created',
    'team.updated': 'Team renamed or edited',
    'team.member_added': 'Member added to a team',
    'team.member_removed': 'Member removed from a team',
    # Organisation
    'organization.created': 'Organisation created',
    'organization.settings_changed': 'Organisation branding changed',
    'organization.terminology_changed': 'Terminology changed',
    'organization.exported': 'Organisation data exported',
    'organization.imported': 'Organisation created from an exported archive',
    # Deleted records
    'rock.deleted': '{rock} deleted',
    'todo.deleted': '{todo} deleted',
    'issue.deleted': '{issue} deleted',
    'scorecard.deleted': '{scorecard} deleted',
    'scorecard.metric_removed': 'Metric removed from a {scorecard}',
    'chart.node_deleted': '{seat} or department deleted from the {accountability_chart}',
    'chart.role_deleted': 'Accountability removed from the {accountability_chart}',
    'vision.core_value_deleted': '{core_value} deleted',
    'vision.section_cleared': '{vto} section cleared',
}


def describe(action, terms=None):
    """A short description of ``action`` in the organisation's words, or '' if unknown."""
    template = EVENTS.get(action, '')
    if not template or '{' not in template:
        return template
    if terms is None:
        from apps.accounts.terminology import Terms
        terms = Terms()
    return template.format_map(terms.as_dict())
