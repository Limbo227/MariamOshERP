from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    pass


class Company(models.Model):
    name = models.CharField("Название", max_length=160)
    code = models.SlugField(unique=True)
    timezone = models.CharField("Часовой пояс", max_length=64, default="Asia/Bishkek")

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
        labels = getattr(self, "_permission_labels", None)
        if labels is None:
            labels = {
                f"{app}.{code}"
                for app, code in self.role.permissions.values_list("content_type__app_label", "codename")
            }
            self._permission_labels = labels
        return permission in labels

    def __str__(self):
        return f"{self.user} / {self.company}"


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
        verbose_name = "Событие аудита"
        verbose_name_plural = "События аудита"


class OperationKey(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    command = models.CharField(max_length=64)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    result_label = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "key"], name="unique_operation_key")]
        verbose_name = "Ключ операции"
        verbose_name_plural = "Ключи операций"

    def __str__(self):
        return f"{self.command} {self.key}"

