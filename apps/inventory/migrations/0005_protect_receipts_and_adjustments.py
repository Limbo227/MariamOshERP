from django.db import migrations

FORWARD = """
CREATE FUNCTION ebb_forbid_posted_receipt_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'POSTED' THEN
        RAISE EXCEPTION 'Проведённый приход не изменяется';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER receipt_no_posted_mutation
BEFORE UPDATE OR DELETE ON inventory_goodsreceipt
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_posted_receipt_mutation();

CREATE FUNCTION ebb_forbid_posted_receipt_line_mutation() RETURNS trigger
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
    SELECT state INTO doc_state FROM inventory_goodsreceipt WHERE id = doc_id;
    IF doc_state = 'POSTED' THEN
        RAISE EXCEPTION 'Проведённые строки прихода не изменяются';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER receipt_line_no_posted_mutation
BEFORE INSERT OR UPDATE OR DELETE ON inventory_receiptline
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_posted_receipt_line_mutation();

CREATE FUNCTION ebb_forbid_posted_adjustment_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'POSTED' THEN
        RAISE EXCEPTION 'Проведённая корректировка не изменяется';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER adjustment_no_posted_mutation
BEFORE UPDATE OR DELETE ON inventory_stockadjustment
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_posted_adjustment_mutation();

CREATE FUNCTION ebb_forbid_posted_adjustment_line_mutation() RETURNS trigger
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
    SELECT state INTO doc_state FROM inventory_stockadjustment WHERE id = doc_id;
    IF doc_state = 'POSTED' THEN
        RAISE EXCEPTION 'Проведённые строки корректировки не изменяются';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER adjustment_line_no_posted_mutation
BEFORE INSERT OR UPDATE OR DELETE ON inventory_adjustmentline
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_posted_adjustment_line_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS adjustment_line_no_posted_mutation ON inventory_adjustmentline;
DROP FUNCTION IF EXISTS ebb_forbid_posted_adjustment_line_mutation();
DROP TRIGGER IF EXISTS adjustment_no_posted_mutation ON inventory_stockadjustment;
DROP FUNCTION IF EXISTS ebb_forbid_posted_adjustment_mutation();
DROP TRIGGER IF EXISTS receipt_line_no_posted_mutation ON inventory_receiptline;
DROP FUNCTION IF EXISTS ebb_forbid_posted_receipt_line_mutation();
DROP TRIGGER IF EXISTS receipt_no_posted_mutation ON inventory_goodsreceipt;
DROP FUNCTION IF EXISTS ebb_forbid_posted_receipt_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_goodsreceipt_order_goodsreceipt_supplier_and_more")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
