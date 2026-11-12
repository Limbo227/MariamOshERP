from django.contrib.auth.models import Group

BOSS_GROUP = "boss"


def ensure_boss_group():
    group, _created = Group.objects.get_or_create(name=BOSS_GROUP)
    return group


def user_can_use_erp(user):
    """Boss-group members and active superusers may open the workplace."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=BOSS_GROUP).exists()
