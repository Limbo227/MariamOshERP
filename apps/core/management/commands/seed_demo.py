from django.core.management.base import BaseCommand

from apps.core.seed import seed


class Command(BaseCommand):
    help = "Load synthetic Mariam-Osh demo data. Safe to run more than once."

    def handle(self, *args, **options):
        seed()
        self.stdout.write(self.style.SUCCESS("Synthetic demo data is ready."))
