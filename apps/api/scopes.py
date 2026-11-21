"""The scopes an API token can carry: one per resource and direction.

Only read scopes exist so far. A write scope is added with the first write
endpoint for its resource, so no token can hold a scope that means nothing.
"""
from oauth2_provider.scopes import BaseScopes

ORGANISATION_READ = 'organisation:read'
TEAMS_READ = 'teams:read'
PRIORITIES_READ = 'priorities:read'
ACTIONS_READ = 'actions:read'
BLOCKERS_READ = 'blockers:read'
METRICS_BOARDS_READ = 'metrics-boards:read'
MEETINGS_READ = 'meetings:read'
VISION_BOARD_READ = 'vision-board:read'
ORG_CHART_READ = 'org-chart:read'

SCOPES = {
    ORGANISATION_READ: 'See the organisation\'s name, branding and vocabulary',
    TEAMS_READ: 'See the organisation\'s teams',
    PRIORITIES_READ: 'See priorities, their steps and check-ins',
    ACTIONS_READ: 'See actions',
    BLOCKERS_READ: 'See blockers',
    METRICS_BOARDS_READ: 'See metrics boards, their metrics and the values entered for them',
    MEETINGS_READ: 'See meetings: agenda, notes, updates, ratings and key messages',
    VISION_BOARD_READ: 'See the organisation\'s vision document and its values',
    ORG_CHART_READ: 'See the organisation\'s chart of roles and who holds each one',
}

# What a client gets when it asks for no scope at all: the least there is.
DEFAULT_SCOPES = [ORGANISATION_READ]


class ApiScopes(BaseScopes):
    def get_all_scopes(self):
        return dict(SCOPES)

    def get_available_scopes(self, application=None, request=None, *args, **kwargs):
        return list(SCOPES)

    def get_default_scopes(self, application=None, request=None, *args, **kwargs):
        return list(DEFAULT_SCOPES)
