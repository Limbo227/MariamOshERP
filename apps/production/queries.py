from apps.inventory.models import Product
from apps.production.models import ProductionReport


def wheat_not_entered(report: ProductionReport):
    return not report.inputs.filter(product__kind=Product.Kind.WHEAT).exists()
