"""Cursor paging: a page stays correct while records are being added.

Each list names the orderings it allows. The position in the list is taken
from the first field and the id breaks ties, so the order is total and two
requests never disagree about it.
"""
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination

DEFAULT_ORDERINGS = {
    'id': ('id',),
    '-id': ('-id',),
    'updated_at': ('updated_at', 'id'),
    '-updated_at': ('-updated_at', '-id'),
}


class ApiCursorPagination(CursorPagination):
    page_size = 50
    max_page_size = 200
    page_size_query_param = 'limit'
    ordering = 'id'
    page_size_query_description = 'How many results to return per page: 50 unless given, 200 at most.'
    cursor_query_description = 'Where to continue from. Follow the `next` and `previous` links; do not build one.'

    def get_ordering(self, request, queryset, view):
        orderings = getattr(view, 'orderings', DEFAULT_ORDERINGS)
        default = getattr(view, 'default_ordering', 'id')
        name = request.query_params.get('ordering', default)
        if name not in orderings:
            raise ValidationError({'ordering': f'Choose one of: {", ".join(orderings)}.'})
        return orderings[name]

    def get_page_size(self, request):
        raw = request.query_params.get(self.page_size_query_param)
        if raw is None:
            return self.page_size
        try:
            size = int(raw)
        except ValueError:
            size = 0
        if size < 1:
            raise ValidationError({'limit': f'Enter a whole number from 1 to {self.max_page_size}.'})
        return min(size, self.max_page_size)

    def get_schema_operation_parameters(self, view):
        parameters = super().get_schema_operation_parameters(view)
        orderings = getattr(view, 'orderings', DEFAULT_ORDERINGS)
        parameters.append({
            'name': 'ordering', 'required': False, 'in': 'query',
            'description': 'Sort order. A leading minus means newest or highest first.',
            'schema': {
                'type': 'string', 'enum': list(orderings),
                'default': getattr(view, 'default_ordering', 'id'),
            },
        })
        return parameters
