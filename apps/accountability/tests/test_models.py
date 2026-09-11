from django.test import TestCase
from django.contrib.auth.models import User
from apps.accounts.models import Organization
from apps.accountability.models import AccountabilityNode, AccountabilityRole


def make_org():
    return Organization.objects.get_or_create(name='Acct Org')[0]


def make_node(name='CEO', node_type=AccountabilityNode.TYPE_SEAT, owner=None, parent=None):
    org = make_org()
    return AccountabilityNode.objects.create(
        organization=org, name=name, node_type=node_type,
        owner=owner, parent=parent,
    )


class AccountabilityNodeTest(TestCase):
    def test_str(self):
        node = make_node(name='CEO')
        self.assertIn('CEO', str(node))
        self.assertIn('Acct Org', str(node))

    def test_vacant_when_no_owner(self):
        node = make_node(owner=None)
        self.assertTrue(node.is_vacant)

    def test_not_vacant_when_owner_set(self):
        user = User.objects.get_or_create(username='acctuser')[0]
        node = make_node(owner=user)
        self.assertFalse(node.is_vacant)

    def test_default_type_is_seat(self):
        node = make_node()
        self.assertEqual(node.node_type, AccountabilityNode.TYPE_SEAT)

    def test_department_type(self):
        node = make_node(node_type=AccountabilityNode.TYPE_DEPARTMENT)
        self.assertEqual(node.node_type, AccountabilityNode.TYPE_DEPARTMENT)


class AccountabilityRoleTest(TestCase):
    def test_str(self):
        node = make_node(name='COO')
        role = AccountabilityRole.objects.create(node=node, description='Manage operations')
        self.assertEqual(str(role), 'Manage operations')

    def test_roles_belong_to_node(self):
        node = make_node(name='CFO')
        AccountabilityRole.objects.create(node=node, description='Oversee finances')
        AccountabilityRole.objects.create(node=node, description='Approve budgets')
        self.assertEqual(node.roles.count(), 2)


class AccountabilityHierarchyTest(TestCase):
    def test_parent_child_relationship(self):
        org = make_org()
        parent = AccountabilityNode.objects.create(organization=org, name='Executive', node_type=AccountabilityNode.TYPE_DEPARTMENT)
        child = AccountabilityNode.objects.create(organization=org, name='CEO', parent=parent)
        self.assertEqual(child.parent, parent)
        self.assertIn(child, parent.children.all())
