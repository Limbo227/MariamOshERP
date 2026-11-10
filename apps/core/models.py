from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    pass


class Company(models.Model):
    name = models.CharField("Название", max_length=160)
    code = models.SlugField(unique=True)

    class Meta:
        verbose_name = "Предприятие"
        verbose_name_plural = "Предприятия"

    def __str__(self):
        return self.name


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    role = models.ForeignKey(Group, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "company"], name="unique_membership")]

    def allows(self, permission):
        app_label, codename = permission.split(".")
        return self.role.permissions.filter(content_type__app_label=app_label, codename=codename).exists()


class WarehouseGrant(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    warehouse = models.ForeignKey("inventory.Warehouse", on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "warehouse"], name="unique_warehouse_grant")]

    def clean(self):
        if self.membership_id and self.warehouse_id:
            if self.membership.company_id != self.warehouse.company_id:
                raise ValidationError("Склад и сотрудник должны относиться к одному предприятию.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AuditEvent(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=64)
    object_label = models.CharField(max_length=160)
    recorded_at = models.DateTimeField(auto_now_add=True)
    detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-recorded_at", "-pk"]
        permissions = [("view_workspace", "Доступ к рабочему месту")]

