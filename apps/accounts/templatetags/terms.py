from django import template

from apps.accounts.terminology import Terms

register = template.Library()


@register.simple_tag(takes_context=True)
def term(context, key, count=None, plural=False, lower=False):
    """``{% term 'rock' %}``, ``{% term 'rock' count=n %}``, ``{% term 'rock' plural=True as name %}``.

    Falls back to the defaults when rendered without the context processor,
    as emails are.
    """
    terms = context.get('terms') or Terms()
    return terms.get(key, count=count, plural=plural, lower=lower)
