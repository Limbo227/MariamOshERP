from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import Currency, FrozenLine, LedgerRow


class MoneyAccount(models.Model):
    class Kind(models.TextChoices):
        CASH = "CASH", "Касса"
        BANK = "BANK", "Банк"

    name = models.CharField("Название", max_length=80, unique=True)
    kind = models.CharField("Тип", max_length=8, choices=Kind.choices)
    currency = models.CharField("Валюта", max_length=3, choices=Currency.choices, default=Currency.KGS)
    overdraft_limit = models.DecimalField("Допустимый минус", max_digits=18, decimal_places=2, default=Decimal("0"))
    active = models.BooleanField("Активен", default=True)

    class Meta:
        db_table = "money_account"
        ordering = ["kind", "name"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["CASH", "BANK"]), name="money_account_kind"),
            models.CheckConstraint(condition=Q(currency__in=["KGS", "RUB", "USD", "KZT"]), name="money_account_currency"),
            models.CheckConstraint(condition=Q(overdraft_limit__gte=0), name="overdraft_nonnegative"),
        ]
        verbose_name = "Касса или банк"
        verbose_name_plural = "Кассы и банки"

    def clean(self):
        if self.pk:
            previous = MoneyAccount.objects.get(pk=self.pk)
            used = self.moves.exists() or self.opening_lines.exists() or self.money_documents.exists()
            if used and previous.currency != self.currency:
                raise ValidationError("Валюту счёта нельзя сменить после движений.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} {self.currency}"


class CashOperation(models.Model):
    """A cashier action that can be added without a schema change.

    `effect` is the only posting switch. Renaming the row does not rewrite history.
    """

    class Effect(models.TextChoices):
        PAY_PARTY = "PAY_PARTY", "Оплата контрагенту"
        RECEIVE_FROM_PARTY = "RECEIVE_FROM_PARTY", "Поступление от контрагента"
        PAY_EXPENSE = "PAY_EXPENSE", "Оплата расхода"
        TRANSFER = "TRANSFER", "Перевод между нашими счетами"
        CONVERT = "CONVERT", "Обмен валюты"
        ACCOUNTABLE = "ACCOUNTABLE", "Выдача под отчёт"
        ACCOUNTABLE_RETURN = "ACCOUNTABLE_RETURN", "Возврат подотчёта"
        SHIPMENT_EXPENSE = "SHIPMENT_EXPENSE", "Расход поставки"

    class Category(models.TextChoices):
        PROCUREMENT = "PROCUREMENT", "Закупка"
        TRANSPORT = "TRANSPORT", "Перевозка"
        CUSTOMS = "CUSTOMS", "Таможня"
        BANKING = "BANKING", "Банк"
        OPERATING = "OPERATING", "Хозяйственные"
        TAX = "TAX", "Налоги"

    code = models.SlugField("Код", unique=True)
    name = models.CharField("Название", max_length=120)
    effect = models.CharField("Смысл", max_length=24, choices=Effect.choices)
    category = models.CharField("Группа расхода", max_length=16, choices=Category.choices, blank=True)
    source_kind = models.CharField("Откуда", max_length=8, blank=True)
    destination_kind = models.CharField("Куда", max_length=8, blank=True)
    active = models.BooleanField("Доступна", default=True)

    class Meta:
        db_table = "cash_operation"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    effect__in=[
                        "PAY_PARTY",
                        "RECEIVE_FROM_PARTY",
                        "PAY_EXPENSE",
                        "TRANSFER",
                        "CONVERT",
                        "ACCOUNTABLE",
                        "ACCOUNTABLE_RETURN",
                        "SHIPMENT_EXPENSE",
                    ]
                ),
                name="operation_effect",
            ),
            models.CheckConstraint(
                condition=Q(source_kind__in=["", "CASH", "BANK"]) & Q(destination_kind__in=["", "CASH", "BANK"]),
                name="operation_account_kind",
            ),
            models.CheckConstraint(
                condition=Q(effect__in=["TRANSFER", "CONVERT"]) | (Q(source_kind="") & Q(destination_kind="")),
                name="operation_transfer_kinds",
            ),
            models.CheckConstraint(
                condition=(
                    Q(effect="PAY_EXPENSE", category__in=["PROCUREMENT", "TRANSPORT", "CUSTOMS", "BANKING", "OPERATING", "TAX"])
                    | (~Q(effect="PAY_EXPENSE") & Q(category=""))
                ),
                name="operation_category",
            ),
        ]
        verbose_name = "Денежная операция"
        verbose_name_plural = "Денежные операции"

    def clean(self):
        if self.pk:
            previous = CashOperation.objects.get(pk=self.pk)
            used = self.money_documents.exists() or self.moves.exists()
            if used and previous.effect != self.effect:
                raise ValidationError("Нельзя менять смысл операции, по которой уже есть проводки.")
        if self.effect == self.Effect.PAY_EXPENSE and not self.category:
            raise ValidationError("У расхода укажите группу.")
        if self.effect != self.Effect.PAY_EXPENSE and self.category:
            raise ValidationError("Группу указывают только у расхода.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk and (self.money_documents.exists() or self.moves.exists()):
            raise ValidationError("Операцию с проводками нельзя удалить. Отключите её.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.name


class ExpenseCategory(models.Model):
    name = models.CharField("Название", max_length=120)
    code = models.CharField("Код", max_length=40, unique=True)
    description = models.TextField("Описание", blank=True)
    active = models.BooleanField("Действует", default=True)

    class Meta:
        db_table = "expense_category"
        ordering = ["name"]
        verbose_name = "Категория расхода"
        verbose_name_plural = "Категории расходов"

    def __str__(self):
        return self.name


class MoneyDocument(models.Model):
    document = models.OneToOneField("core.Document", on_delete=models.PROTECT, related_name="money")
    operation = models.ForeignKey(CashOperation, on_delete=models.PROTECT, related_name="money_documents")
    account = models.ForeignKey(MoneyAccount, on_delete=models.PROTECT, related_name="money_documents")
    counter_account = models.ForeignKey(
        MoneyAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_money_documents"
    )
    party = models.ForeignKey("core.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="money_documents")
    order = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    shipment = models.ForeignKey(
        "procurement.Shipment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expenses",
    )
    expense_category = models.ForeignKey(
        ExpenseCategory,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="money_documents",
        verbose_name="Категория расхода",
    )
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)
    destination_amount = models.DecimalField("Сумма зачисления", max_digits=18, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField("Курс", max_digits=30, decimal_places=12, null=True, blank=True)
    external_reference = models.CharField("Внешний номер", max_length=80, blank=True)

    class Meta:
        db_table = "money_document"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="money_document_amount"),
            models.CheckConstraint(
                condition=Q(destination_amount__isnull=True) | Q(destination_amount__gt=0),
                name="money_destination_amount",
            ),
            models.CheckConstraint(condition=Q(rate__isnull=True) | Q(rate__gt=0), name="money_rate"),
        ]
        verbose_name = "Денежный документ"
        verbose_name_plural = "Денежные документы"

    def clean(self):
        if not self.operation_id:
            return
        effect = self.operation.effect
        expense_effect = effect in (CashOperation.Effect.PAY_EXPENSE, CashOperation.Effect.SHIPMENT_EXPENSE)
        exchange = effect in (CashOperation.Effect.TRANSFER, CashOperation.Effect.CONVERT)
        if exchange:
            if self.party_id:
                raise ValidationError("Перевод между своими счетами не относится к контрагенту.")
            if not self.counter_account_id or self.counter_account_id == self.account_id:
                raise ValidationError("Укажите два разных наших счёта.")
            if self.destination_amount is None or self.rate is None:
                raise ValidationError("Укажите сумму зачисления и курс.")
        elif self.counter_account_id:
            raise ValidationError("Второй счёт нужен только для перевода.")
        if effect == CashOperation.Effect.PAY_EXPENSE and self.party_id and not self.party.is_employee:
            raise ValidationError("В расходе контрагентом может быть только сотрудник с подотчётом.")
        if effect == CashOperation.Effect.SHIPMENT_EXPENSE:
            if not self.expense_category_id:
                raise ValidationError("Укажите категорию расхода.")
            if not self.order_id and not self.shipment_id:
                raise ValidationError("Укажите поставку или спецификацию.")
        if (self.order_id or self.shipment_id) and not expense_effect:
            raise ValidationError("Закупку и поставку указывают только у расхода.")
        if self.shipment_id and self.order_id and self.shipment.order_id != self.order_id:
            raise ValidationError("Поставка относится к другой спецификации.")
        if effect in (CashOperation.Effect.PAY_PARTY, CashOperation.Effect.RECEIVE_FROM_PARTY) and not self.party_id:
            raise ValidationError("Укажите контрагента.")
        if self.operation.source_kind and self.account_id and self.account.kind != self.operation.source_kind:
            raise ValidationError("Эта операция проводится с другого типа счёта.")
        if self.operation.destination_kind and self.counter_account_id and self.counter_account.kind != self.operation.destination_kind:
            raise ValidationError("Эта операция зачисляется на другой тип счёта.")

    def rate_display(self):
        from apps.core.quantities import display_rate

        if self.rate is None:
            return None
        return display_rate(self.rate)

    rate_display.short_description = "Курс"

    def save(self, *args, **kwargs):
        from apps.core.lifecycle import lifecycle_open

        if self.document.state != self.document.State.DRAFT and not lifecycle_open():
            raise ValidationError("Денежный документ изменяется только в черновике. Сначала отмените выполнение.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return str(self.document)


class OpeningMoneyLine(FrozenLine):
    opening = models.ForeignKey("core.OpeningBalance", on_delete=models.PROTECT, related_name="money_lines")
    account = models.ForeignKey(MoneyAccount, on_delete=models.PROTECT, related_name="opening_lines")
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)

    class Meta:
        db_table = "opening_money_line"
        constraints = [models.CheckConstraint(condition=~Q(amount=0), name="opening_money_nonzero")]
        verbose_name = "Начальный остаток денег"
        verbose_name_plural = "Начальные остатки денег"

    def document_for_edit(self):
        return self.opening.document


class OpeningPartyLine(FrozenLine):
    class Side(models.TextChoices):
        WE_OWE = "WE_OWE", "Мы должны"
        THEY_OWE = "THEY_OWE", "Нам должны"

    class Lane(models.TextChoices):
        PAYABLE = "PAYABLE", "Расчёты с поставщиком"
        RECEIVABLE = "RECEIVABLE", "Расчёты с покупателем"

    opening = models.ForeignKey("core.OpeningBalance", on_delete=models.PROTECT, related_name="party_lines")
    party = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="opening_lines")
    side = models.CharField("Сторона", max_length=12, choices=Side.choices)
    lane = models.CharField("Раздел", max_length=12, choices=Lane.choices)
    currency = models.CharField("Валюта", max_length=3, choices=Currency.choices, default=Currency.KGS)
    amount = models.DecimalField("Сумма", max_digits=18, decimal_places=2)

    class Meta:
        db_table = "opening_party_line"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="opening_party_amount"),
            models.CheckConstraint(condition=Q(side__in=["WE_OWE", "THEY_OWE"]), name="opening_party_side"),
            models.CheckConstraint(condition=Q(lane__in=["PAYABLE", "RECEIVABLE"]), name="opening_party_lane"),
            models.CheckConstraint(condition=Q(currency__in=["KGS", "RUB", "USD", "KZT"]), name="opening_party_currency"),
        ]
        verbose_name = "Начальный долг"
        verbose_name_plural = "Начальные долги"

    def document_for_edit(self):
        return self.opening.document


class MoneyMove(LedgerRow):
    document = models.ForeignKey("core.Document", on_delete=models.PROTECT, related_name="money_moves")
    account = models.ForeignKey(MoneyAccount, on_delete=models.PROTECT, related_name="moves")
    operation = models.ForeignKey(CashOperation, null=True, blank=True, on_delete=models.PROTECT, related_name="moves")
    amount_delta = models.DecimalField(max_digits=18, decimal_places=2)
    pair = models.UUIDField(null=True, blank=True)
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "money_move"
        constraints = [models.CheckConstraint(condition=~Q(amount_delta=0), name="money_nonzero")]
        indexes = [models.Index(fields=["account", "effective_date"], name="money_account_date")]
        verbose_name = "Движение денег"
        verbose_name_plural = "Движения денег"


class OpenItem(LedgerRow):
    class Side(models.TextChoices):
        WE_OWE = "WE_OWE", "Мы должны"
        THEY_OWE = "THEY_OWE", "Нам должны"

    class Lane(models.TextChoices):
        PAYABLE = "PAYABLE", "Расчёты с поставщиком"
        RECEIVABLE = "RECEIVABLE", "Расчёты с покупателем"
        ACCOUNTABLE = "ACCOUNTABLE", "Подотчёт"

    document = models.ForeignKey("core.Document", on_delete=models.PROTECT, related_name="open_items")
    party = models.ForeignKey("core.Party", on_delete=models.PROTECT, related_name="open_items")
    order = models.ForeignKey(
        "procurement.PurchaseOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="open_items",
    )
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.KGS)
    side = models.CharField(max_length=12, choices=Side.choices)
    lane = models.CharField(max_length=12, choices=Lane.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    effective_date = models.DateField()
    memo = models.CharField(max_length=160, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "open_item"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="open_item_amount"),
            models.CheckConstraint(condition=Q(side__in=["WE_OWE", "THEY_OWE"]), name="open_item_side"),
            models.CheckConstraint(
                condition=Q(lane__in=["PAYABLE", "RECEIVABLE", "ACCOUNTABLE"]),
                name="open_item_lane",
            ),
            models.CheckConstraint(condition=Q(currency__in=["KGS", "RUB", "USD", "KZT"]), name="open_item_currency"),
        ]
        indexes = [models.Index(fields=["party", "lane", "effective_date"], name="open_item_party")]
        verbose_name = "Открытая позиция"
        verbose_name_plural = "Открытые позиции"

    def __str__(self):
        return f"{self.get_side_display()} {self.amount} {self.party}"


class Allocation(LedgerRow):
    document = models.ForeignKey("core.Document", on_delete=models.PROTECT, related_name="allocations")
    we_owe = models.ForeignKey(OpenItem, on_delete=models.PROTECT, related_name="allocations_as_debt")
    they_owe = models.ForeignKey(OpenItem, on_delete=models.PROTECT, related_name="allocations_as_credit")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "allocation"
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="allocation_amount")]
        verbose_name = "Зачёт"
        verbose_name_plural = "Зачёты"

    def clean(self):
        if self.we_owe_id and self.we_owe.side != OpenItem.Side.WE_OWE:
            raise ValidationError("Зачёт закрывает позицию «мы должны».")
        if self.they_owe_id and self.they_owe.side != OpenItem.Side.THEY_OWE:
            raise ValidationError("Зачёт закрывает позицию «нам должны».")
        if self.we_owe_id and self.they_owe_id and self.we_owe.party_id != self.they_owe.party_id:
            raise ValidationError("Зачёт только внутри одного контрагента.")
        if self.we_owe_id and self.they_owe_id and self.we_owe.lane != self.they_owe.lane:
            raise ValidationError("Зачёт не смешивает долг поставщику и долг покупателя.")
