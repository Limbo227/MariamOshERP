"""Shared parties, documents, and numbering.

One installation, one organization. Balances are sums of posted rows in the
domain apps. This module does not price stock.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Currency(models.TextChoices):
    KGS = "KGS", "KGS"
    RUB = "RUB", "RUB"
    USD = "USD", "USD"
    KZT = "KZT", "KZT"


class User(AbstractUser):
    """Login for this installation."""

    groups = models.ManyToManyField(
        "auth.Group",
        verbose_name="groups",
        blank=True,
        help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
        related_name="user_set",
        related_query_name="user",
        db_table="user_group",
    )
    user_permissions = models.ManyToManyField(
        "auth.Permission",
        verbose_name="user permissions",
        blank=True,
        help_text="Specific permissions for this user.",
        related_name="user_set",
        related_query_name="user",
        db_table="user_permission",
    )

    class Meta:
        db_table = "user"
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"


class Organization(models.Model):
    legal_name = models.CharField("Название", max_length=160)
    currency = models.CharField("Валюта учёта", max_length=3, default="KGS")
    timezone = models.CharField("Часовой пояс", max_length=64, default="Asia/Bishkek")
    singleton = models.BooleanField(default=True, editable=False, unique=True)

    class Meta:
        db_table = "organization"
        verbose_name = "Организация"
        verbose_name_plural = "Организация"

    def save(self, *args, **kwargs):
        if not self.pk and Organization.objects.exists():
            raise ValidationError("В этой базе ведётся одна организация.")
        if self.pk:
            previous = Organization.objects.get(pk=self.pk)
            from apps.finance.models import MoneyMove, OpenItem

            moved = MoneyMove.objects.exists() or OpenItem.objects.exists()
            if previous.currency != self.currency and moved:
                raise ValidationError("Валюту нельзя сменить после денежных записей.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Карточка организации не удаляется.")

    def __str__(self):
        return self.legal_name


class Party(models.Model):
    name = models.CharField("Название", max_length=160)
    is_supplier = models.BooleanField("Поставщик", default=False)
    is_customer = models.BooleanField("Покупатель", default=False)
    is_employee = models.BooleanField("Сотрудник", default=False)
    active = models.BooleanField("Активен", default=True)
    note = models.TextField("Заметка", blank=True)

    class Meta:
        db_table = "party"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_supplier=True) | Q(is_customer=True) | Q(is_employee=True),
                name="party_has_role",
            ),
        ]
        verbose_name = "Контрагент"
        verbose_name_plural = "Контрагенты"

    def clean(self):
        if not self.is_supplier and not self.is_customer and not self.is_employee:
            raise ValidationError("Отметьте поставщика, покупателя или сотрудника.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class NumberSequence(models.Model):
    kind = models.CharField(max_length=16, unique=True)
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "number_sequence"

    def __str__(self):
        return self.kind


class Document(models.Model):
    class Kind(models.TextChoices):
        PURCHASE = "PURCHASE", "Закупка"
        RECEIPT = "RECEIPT", "Приёмка"
        SALE = "SALE", "Продажа"
        ISSUE = "ISSUE", "Выдача"
        MONEY = "MONEY", "Деньги"
        PRODUCTION = "PRODUCTION", "Выпуск"
        OPENING = "OPENING", "Начальные остатки"
        SETTLEMENT = "SETTLEMENT", "Зачёт"
        REVERSAL = "REVERSAL", "Сторно"

    class State(models.TextChoices):
        DRAFT = "DRAFT", "Черновик"
        POSTED = "POSTED", "Проведён"

    kind = models.CharField("Тип", max_length=16, choices=Kind.choices)
    number = models.CharField("Номер", max_length=32, unique=True)
    state = models.CharField("Состояние", max_length=8, choices=State.choices, default=State.DRAFT)
    effective_date = models.DateField("Дата")
    note = models.TextField("Комментарий", blank=True)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal", verbose_name="Сторнирует"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="acted_documents"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "document"
        ordering = ["-effective_date", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["PURCHASE", "RECEIPT", "SALE", "ISSUE", "MONEY", "PRODUCTION", "OPENING", "SETTLEMENT", "REVERSAL"]),
                name="document_kind",
            ),
            models.CheckConstraint(condition=Q(state__in=["DRAFT", "POSTED"]), name="document_state"),
            models.CheckConstraint(
                condition=Q(state="DRAFT", posted_at__isnull=True) | Q(state="POSTED", posted_at__isnull=False),
                name="document_posted_at",
            ),
            models.CheckConstraint(
                condition=Q(kind="REVERSAL", reverses__isnull=False) | (~Q(kind="REVERSAL") & Q(reverses__isnull=True)),
                name="reversal_link",
            ),
        ]
        verbose_name = "Документ"
        verbose_name_plural = "Документы"

    def save(self, *args, **kwargs):
        from apps.core.lifecycle import lifecycle_open

        if self.pk and not lifecycle_open():
            previous = Document.objects.get(pk=self.pk)
            if previous.state == self.State.POSTED:
                raise ValidationError("Проведённый документ не изменяется. Сначала отмените выполнение.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from apps.core.lifecycle import lifecycle_open

        if self.state != self.State.DRAFT:
            raise ValidationError("Проведённый документ нельзя удалить. Сначала отмените выполнение.")
        if not lifecycle_open():
            raise ValidationError("Черновик удаляется через сервис документа.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.get_kind_display()} {self.number}"


class FrozenLine(models.Model):
    class Meta:
        abstract = True

    def document_for_edit(self):
        raise NotImplementedError

    def save(self, *args, **kwargs):
        from apps.core.lifecycle import lifecycle_open

        document = self.document_for_edit()
        if document is not None and document.state != Document.State.DRAFT and not lifecycle_open():
            if self.pk:
                raise ValidationError("Строка проведённого документа не изменяется.")
            raise ValidationError("Нельзя добавлять строки в проведённый документ.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from apps.core.lifecycle import lifecycle_open

        document = self.document_for_edit()
        if document is not None and document.state != Document.State.DRAFT and not lifecycle_open():
            raise ValidationError("Строка проведённого документа не удаляется.")
        return super().delete(*args, **kwargs)


class LedgerRow(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Проведённая запись не изменяется.")
        if self.document_id and self.document.state != Document.State.DRAFT:
            raise ValidationError("Нельзя добавить проводку к проведённому документу.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Проведённая запись не удаляется.")


class OpeningBalance(models.Model):
    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name="opening")

    class Meta:
        db_table = "opening_balance"
        verbose_name = "Начальные остатки"
        verbose_name_plural = "Начальные остатки"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Начальные остатки не изменяются.")
        if self.document.state != Document.State.DRAFT:
            raise ValidationError("Начальные остатки создаются до проведения.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.document)


class AuditEntry(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Создан"
        UPDATED = "UPDATED", "Изменён"
        POSTED = "POSTED", "Выполнено"
        UNPOSTED = "UNPOSTED", "Отменено выполнение"
        DELETED = "DELETED", "Удалён черновик"

    action = models.CharField("Действие", max_length=16, choices=Action.choices)
    document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )
    document_number = models.CharField(max_length=32, blank=True)
    document_kind = models.CharField(max_length=16, blank=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    detail = models.TextField(blank=True)
    snapshot = models.JSONField("Снимок значений", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_entry"
        ordering = ["-created_at", "-pk"]
        verbose_name = "Запись аудита"
        verbose_name_plural = "Журнал аудита"

    def __str__(self):
        return f"{self.get_action_display()} {self.document_number or self.target_id}"
