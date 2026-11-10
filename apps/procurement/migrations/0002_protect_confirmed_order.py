from django.db import migrations

FORWARD = """
CREATE FUNCTION ebb_forbid_confirmed_order_rewrite() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND OLD.state = 'CONFIRMED' THEN
        RAISE EXCEPTION 'Подтверждённый заказ не переписывается';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.state = 'CONFIRMED' AND (
        NEW.company_id IS DISTINCT FROM OLD.company_id
        OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
        OR NEW.currency IS DISTINCT FROM OLD.currency
        OR NEW.reference IS DISTINCT FROM OLD.reference
        OR NEW.contract_reference IS DISTINCT FROM OLD.contract_reference
        OR NEW.effective_date IS DISTINCT FROM OLD.effective_date
        OR NEW.key IS DISTINCT FROM OLD.key
        OR NEW.state IS DISTINCT FROM OLD.state
        OR NEW.actor_id IS DISTINCT FROM OLD.actor_id
    ) THEN
        RAISE EXCEPTION 'Подтверждённый заказ не переписывается';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER order_no_confirmed_rewrite
BEFORE UPDATE OR DELETE ON procurement_purchaseorder
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_confirmed_order_rewrite();

CREATE FUNCTION ebb_forbid_confirmed_order_line_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    order_id bigint;
    order_state text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        order_id := OLD.order_id;
    ELSE
        order_id := NEW.order_id;
    END IF;
    SELECT state INTO order_state FROM procurement_purchaseorder WHERE id = order_id;
    IF order_state = 'CONFIRMED' THEN
        RAISE EXCEPTION 'Подтверждённый заказ не переписывается';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER order_line_no_confirmed_mutation
BEFORE INSERT OR UPDATE OR DELETE ON procurement_orderline
FOR EACH ROW EXECUTE FUNCTION ebb_forbid_confirmed_order_line_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS order_line_no_confirmed_mutation ON procurement_orderline;
DROP FUNCTION IF EXISTS ebb_forbid_confirmed_order_line_mutation();
DROP TRIGGER IF EXISTS order_no_confirmed_rewrite ON procurement_purchaseorder;
DROP FUNCTION IF EXISTS ebb_forbid_confirmed_order_rewrite();
"""


class Migration(migrations.Migration):
    dependencies = [("procurement", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
