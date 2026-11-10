from django.db import migrations

FORWARD = """
CREATE FUNCTION ebb_forbid_stock_ledger_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Проведённая складская запись не изменяется';
END;
$$;

CREATE TRIGGER stock_ledger_no_mutation
BEFORE UPDATE OR DELETE ON inventory_stockledgerentry
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_stock_ledger_mutation();

CREATE FUNCTION ebb_forbid_posted_opening_line_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    doc_id bigint;
    doc_state text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        doc_id := OLD.document_id;
    ELSE
        doc_id := NEW.document_id;
    END IF;
    SELECT state INTO doc_state FROM inventory_openingbalance WHERE id = doc_id;
    IF doc_state = 'POSTED' THEN
        RAISE EXCEPTION 'Проведённые строки начальных остатков не изменяются';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER opening_line_no_posted_mutation
BEFORE INSERT OR UPDATE OR DELETE ON inventory_openingline
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_posted_opening_line_mutation();

CREATE FUNCTION ebb_forbid_posted_opening_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'POSTED' THEN
        RAISE EXCEPTION 'Проведённый документ начальных остатков не изменяется';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER opening_no_posted_mutation
BEFORE UPDATE OR DELETE ON inventory_openingbalance
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_posted_opening_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS opening_no_posted_mutation ON inventory_openingbalance;
DROP FUNCTION IF EXISTS ebb_forbid_posted_opening_mutation();
DROP TRIGGER IF EXISTS opening_line_no_posted_mutation ON inventory_openingline;
DROP FUNCTION IF EXISTS ebb_forbid_posted_opening_line_mutation();
DROP TRIGGER IF EXISTS stock_ledger_no_mutation ON inventory_stockledgerentry;
DROP FUNCTION IF EXISTS ebb_forbid_stock_ledger_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
