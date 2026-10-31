"""Visibility rules shared by detail and interaction endpoints."""
from datetime import datetime, timedelta


def college_domain(user):
    return user.college_domain or user.email.rsplit('@', 1)[-1]


def can_view_marketplace_item(item, user):
    if user.is_admin or item.user_id == user.id:
        return True
    return (
        item.created_at >= datetime.utcnow() - timedelta(days=14)
        and item.user is not None
        and item.user.college_domain == college_domain(user)
    )


def can_view_confession(confession, user):
    if user.is_admin or confession.user_id == user.id:
        return True
    return (
        confession.created_at >= datetime.utcnow() - timedelta(hours=48)
        and (
            confession.scope == 'global'
            or confession.college_domain == college_domain(user)
        )
    )
