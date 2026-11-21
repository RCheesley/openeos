"""One person's data: a copy of it for them, and erasure when they ask for it.

:mod:`.relations` is the single list of every place a record points at a user
account, with what the export and the erasure each do about it. :mod:`.export`
writes the archive a person downloads from their profile; :mod:`.erasure` is
what the ``erase_user`` management command runs.
"""
