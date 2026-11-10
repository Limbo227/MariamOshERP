from django.db import migrations

FORWARD = """
CREATE FUNCTION ebb_forbid_obligation_entry_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Проведённая сумма долга не изменяется';
END;
$$;

CREATE TRIGGER obligation_entry_no_mutation
BEFORE UPDATE OR DELETE ON settlements_obligationentry
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_obligation_entry_mutation();

CREATE FUNCTION ebb_forbid_allocation_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Зачёт оплаты не изменяется';
END;
$$;

CREATE TRIGGER allocation_no_mutation
BEFORE UPDATE OR DELETE ON settlements_paymentallocation
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_allocation_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS allocation_no_mutation ON settlements_paymentallocation;
DROP FUNCTION IF EXISTS ebb_forbid_allocation_mutation();
DROP TRIGGER IF EXISTS obligation_entry_no_mutation ON settlements_obligationentry;
DROP FUNCTION IF EXISTS ebb_forbid_obligation_entry_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("settlements", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
