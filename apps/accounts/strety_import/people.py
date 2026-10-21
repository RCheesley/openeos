"""Match the people named in a Strety export to users of the organisation."""
from django.contrib.auth.models import User
from django.utils.text import slugify

from apps.accounts.models import Membership, UserProfile

from .parsing import is_blank_person


class PeopleResolver:
    """Turn names from the export into users.

    A name is matched, case-insensitively, against members of the organisation
    by full name, then username, then first name when that is unique; the
    importing user wins a tie, and superusers only match when nobody else does. An
    unmatched name is created as a new member when ``create_users`` is set;
    otherwise the importing user stands in wherever a user is required and
    nullable links are left empty. Every unmatched name is remembered so the
    summary can list it.
    """

    def __init__(self, organization, importing_user, create_users=False):
        self.organization = organization
        self.importing_user = importing_user
        self.create_users = create_users
        self.created = []
        self.unmatched = []
        self._cache = {}
        self._members = None

    def resolve(self, name, required=False):
        """Return the user for ``name``; ``None`` (or the importing user) when unknown."""
        fallback = self.importing_user if required else None
        if is_blank_person(name):
            return fallback
        key = name.strip().lower()
        if key not in self._cache:
            user = self._match(key)
            if user is None and self.create_users:
                user = self._create(name.strip())
            if user is None and name.strip() not in self.unmatched:
                self.unmatched.append(name.strip())
            self._cache[key] = user
        return self._cache[key] or fallback

    # ── internals ────────────────────────────────────────────────────────────

    def _members_list(self):
        # The importing user comes first and superusers last, so a name that fits
        # several members (a platform operator who is also a member, say) resolves
        # to the person running the import rather than the operator account.
        if self._members is None:
            members = User.objects.filter(memberships__organization=self.organization).distinct()
            self._members = sorted(
                members, key=lambda u: (u != self.importing_user, u.is_superuser, u.pk)
            )
        return self._members

    def _match(self, key):
        members = self._members_list()
        for user in members:
            if user.get_full_name().strip().lower() == key:
                return user
        for user in members:
            if user.username.lower() == key:
                return user
        by_first_name = [u for u in members if u.first_name.strip().lower() == key]
        if self.importing_user in by_first_name:
            return self.importing_user
        by_first_name = [u for u in by_first_name if not u.is_superuser] or by_first_name
        if len(by_first_name) == 1:
            return by_first_name[0]
        return None

    def _create(self, name):
        first_name, _, last_name = name.partition(' ')
        base = slugify(name) or 'strety-user'
        username, counter = base, 2
        while User.objects.filter(username=username).exists():
            username, counter = f'{base}-{counter}', counter + 1
        user = User(username=username, first_name=first_name[:150], last_name=last_name[:150])
        user.set_unusable_password()
        user.save()
        UserProfile.objects.get_or_create(user=user)
        Membership.objects.create(
            user=user, organization=self.organization, role=Membership.ROLE_MEMBER
        )
        self._members_list().append(user)
        self.created.append((name, username))
        return user
