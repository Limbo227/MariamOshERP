from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION ebb_forbid_confirmed_order_rewrite() RETURNS trigger
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
        OR NEW.batch_number IS DISTINCT FROM OLD.batch_number
        OR NEW.wagon_count IS DISTINCT FROM OLD.wagon_count
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
"""

REVERSE = migrations.RunSQL.noop


class Migration(migrations.Migration):
    dependencies = [("procurement", "0003_customsacceptance_purchaseorder_batch_number_and_more")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
