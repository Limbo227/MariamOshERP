from apps.production.models import ProductionReport


def wheat_not_entered(report: ProductionReport):
    return not report.inputs.exists()
