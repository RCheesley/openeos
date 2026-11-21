"""The organisation's vocabulary under fixed, generic keys.

Internally a term is keyed by the word the code grew up with. The API never
publishes those keys: each has a fixed generic name here, and an organisation's
own words are the values.
"""
from apps.accounts.terminology import PLURAL_KEYS, terms_for
from apps.meetings import segments

API_TERM_KEYS = {
    'rock': 'priority',
    'issue': 'blocker',
    'todo': 'action',
    'scorecard': 'metrics_board',
    'meeting': 'meeting',
    'vto': 'vision_board',
    'accountability_chart': 'org_chart',
    'seat': 'role',
    'core_value': 'value',
    'milestone': 'step',
    'headline': 'update',
    'segue': 'meeting_opener',
    'ids': 'problem_solving',
    'cascading_message': 'key_message',
}

# A meeting's agenda stores each segment under an internal type name. The API
# publishes these instead, built on the vocabulary keys above where one exists.
CUSTOM_SEGMENT = 'custom'
SEGMENT_TYPE_TO_API = {
    segments.CHECK_IN: API_TERM_KEYS['segue'],
    segments.METRICS_REVIEW: f'{API_TERM_KEYS["scorecard"]}_review',
    segments.PRIORITY_REVIEW: f'{API_TERM_KEYS["rock"]}_review',
    segments.UPDATES: f'{API_TERM_KEYS["headline"]}s',
    segments.ACTION_REVIEW: f'{API_TERM_KEYS["todo"]}_review',
    segments.IDS: API_TERM_KEYS['ids'],
    segments.CONCLUDE: 'conclude',
    segments.CUSTOM_NOTES: CUSTOM_SEGMENT,
}
SEGMENT_TYPES = [(value, value.replace('_', ' ').capitalize()) for value in SEGMENT_TYPE_TO_API.values()]


def agenda_for(meeting, terms):
    """A meeting's frozen agenda under the API's segment names.

    ``name`` is the segment's own label where it has one, else the
    organisation's word for that kind of segment.
    """
    return [
        {
            'position': position,
            'type': SEGMENT_TYPE_TO_API.get(entry['segment_type'], CUSTOM_SEGMENT),
            'name': entry['name'],
            'duration_minutes': entry['duration_minutes'],
        }
        for position, entry in enumerate(segments.resolve_agenda(meeting.agenda, terms))
    ]


def vocabulary_for(org):
    terms = terms_for(org).as_dict()
    return {
        api_key: {'singular': terms[key], 'plural': terms[PLURAL_KEYS[key]]}
        for key, api_key in API_TERM_KEYS.items()
    }
