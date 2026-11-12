from django.core.management.base import BaseCommand

from apps.finance.models import CashOperation, ExpenseCategory
from apps.finance.reference_data import seed_expense_categories, seed_shipment_operation
from apps.inventory.models import Warehouse
from apps.inventory.products import ensure_reference_units
from apps.inventory.services import ensure_default_location


class Command(BaseCommand):
    help = "Повторно заполняет единицы, категории товаров, категории расходов и склад по умолчанию."

    def handle(self, *args, **options):
        ensure_reference_units()
        seed_expense_categories(ExpenseCategory)
        seed_shipment_operation(CashOperation)
        for warehouse in Warehouse.objects.all():
            ensure_default_location(warehouse)
        self.stdout.write(self.style.SUCCESS("Справочники заполнены."))
