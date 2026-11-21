from datetime import date, timedelta
from unittest import mock

from django.utils import timezone

from apps.api.throttling import TokenRateThrottle
from apps.rocks.models import Rock

from .helpers import ApiTestCase


class PaginationTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        Rock.objects.all().delete()
        self.rocks = [
            Rock.objects.create(
                title=f'Priority {n}', owner=self.user, team=self.mine['team'],
                quarter=1, year=2026, due_date=date(2026, 3, 31),
            )
            for n in range(7)
        ]

    def walk(self, path):
        """Follow ``next`` links to the end; return the pages of ids."""
        pages, url = [], f'/api/v1/{path}'
        while url:
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {self.token}')
            self.assertEqual(response.status_code, 200, response.content)
            body = response.json()
            self.assertEqual(set(body), {'next', 'previous', 'results'})
            pages.append([row['id'] for row in body['results']])
            url = body['next']
        return pages

    def test_pages_cover_every_record_once_in_id_order(self):
        pages = self.walk('priorities?limit=3')
        self.assertEqual([len(page) for page in pages], [3, 3, 1])
        self.assertEqual(sum(pages, []), [rock.pk for rock in self.rocks])

    def test_same_request_gives_the_same_order(self):
        self.assertEqual(self.walk('priorities?limit=2'), self.walk('priorities?limit=2'))

    def test_descending_order(self):
        ids = sum(self.walk('priorities?limit=4&ordering=-id'), [])
        self.assertEqual(ids, [rock.pk for rock in reversed(self.rocks)])

    def test_ties_on_updated_at_are_broken_by_id(self):
        moment = timezone.now()
        Rock.objects.all().update(updated_at=moment)
        ascending = sum(self.walk('priorities?limit=2&ordering=updated_at'), [])
        self.assertEqual(ascending, [rock.pk for rock in self.rocks])
        descending = sum(self.walk('priorities?limit=2&ordering=-updated_at'), [])
        self.assertEqual(descending, list(reversed(ascending)))

    def test_a_record_added_mid_walk_does_not_shift_the_pages(self):
        first = self.client.get('/api/v1/priorities?limit=3', HTTP_AUTHORIZATION=f'Bearer {self.token}').json()
        late = Rock.objects.create(
            title='Late', owner=self.user, team=self.mine['team'], quarter=1, year=2026, due_date=date(2026, 3, 31),
        )
        rest, url = [], first['next']
        while url:
            body = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {self.token}').json()
            rest += [row['id'] for row in body['results']]
            url = body['next']
        seen = [row['id'] for row in first['results']] + rest
        self.assertEqual(seen, [rock.pk for rock in self.rocks] + [late.pk])

    def test_limit_is_capped_and_validated(self):
        self.assertEqual(len(self.results('priorities?limit=1000')), 7)
        for bad in ('0', '-1', 'lots'):
            with self.subTest(limit=bad):
                body = self.assertProblem(self.api_get(f'priorities?limit={bad}'), 400)
                self.assertIn('limit', body['errors'])

    def test_unknown_ordering_is_refused(self):
        body = self.assertProblem(self.api_get('priorities?ordering=title'), 400)
        self.assertIn('ordering', body['errors'])

    def test_bad_cursor_is_refused(self):
        self.assertProblem(self.api_get('priorities?cursor=nonsense'), 404)

    def test_updated_since_returns_what_changed(self):
        cutoff = timezone.now()
        Rock.objects.all().update(updated_at=cutoff - timedelta(hours=1))
        changed = self.rocks[4]
        Rock.objects.filter(pk=changed.pk).update(updated_at=cutoff + timedelta(seconds=5))
        stamp = cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual([row['id'] for row in self.results(f'priorities?updated_since={stamp}')], [changed.pk])
        self.assertEqual(len(self.results('priorities?updated_since=2000-01-01T00:00:00Z')), 7)
        self.assertProblem(self.api_get('priorities?updated_since=yesterday'), 400)

    def test_filters(self):
        Rock.objects.filter(pk=self.rocks[0].pk).update(status='complete', quarter=2)
        self.assertEqual([r['id'] for r in self.results('priorities?status=complete')], [self.rocks[0].pk])
        self.assertEqual(len(self.results('priorities?quarter=1&year=2026')), 6)
        self.assertProblem(self.api_get('priorities?status=finished'), 400)
        self.assertProblem(self.api_get('priorities?team=alpha'), 400)

    def test_sub_lists_are_paged_too(self):
        rock = self.rocks[0]
        for n in range(4):
            rock.milestones.create(title=f'Step {n}', order=n)
        pages = self.walk(f'priorities/{rock.pk}/steps?limit=3')
        self.assertEqual([len(page) for page in pages], [3, 1])


class ThrottleTest(ApiTestCase):
    def test_requests_are_limited_per_connection(self):
        with mock.patch.object(TokenRateThrottle, 'rate', '2/min', create=True):
            self.assertEqual(self.api_get('me').status_code, 200)
            self.assertEqual(self.api_get('me').status_code, 200)
            response = self.api_get('me')
            self.assertProblem(response, 429)
            self.assertIn('Retry-After', response)
