from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, transaction
from django.urls import reverse

from apps.catalog.models import Product, ProductRequirement
from apps.core.models import AuditEvent, Company, OperationKey, User
from apps.core.seed import DEMO_PASSWORDS
from apps.inventory.models import OpeningBalance, OpeningLine, StockLedgerEntry, Warehouse
from apps.inventory.services import OPENING_COMMAND, DraftLine, create_draft, post_opening

pytestmark = pytest.mark.django_db


def _sack_line(world, quantity="500"):
    return DraftLine(world.sack.pk, world.packaging.pk, Decimal(quantity), None, world.basis)


def test_company_has_one_raw_and_one_finished_warehouse(world):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Warehouse.objects.create(company=world.company, kind=Warehouse.Kind.RAW, name="Лишний склад")


def test_flour_requires_exactly_one_matching_sack(world):
    assert world.flour.requirement.component_id == world.sack.pk
    with pytest.raises(ValidationError):
        ProductRequirement.objects.create(product=world.flour, component=world.wheat)
    other = Company.objects.create(name="Другое", code="other-mill")
    foreign_sack = Product.objects.create(company=other, sku="SACK-X", name="Чужой мешок", kind=Product.Kind.SACK, unit=Product.Unit.PCS)
    foreign_flour = Product.objects.create(
        company=other, sku="FLOUR-X", name="Чужая мука", kind=Product.Kind.FLOUR, unit=Product.Unit.KG, package_kg=Decimal("50")
    )
    with pytest.raises(ValidationError):
        ProductRequirement.objects.create(product=foreign_flour, component=world.sack)
    ProductRequirement.objects.create(product=foreign_flour, component=foreign_sack)


def test_invalid_later_line_rolls_back_the_whole_draft(world):
    other = Company.objects.create(name="Другое", code="other-mill")
    foreign = Product.objects.create(company=other, sku="WHEAT-X", name="Чужая пшеница", kind=Product.Kind.WHEAT, unit=Product.Unit.KG)
    with pytest.raises(ValidationError):
        create_draft(
            membership=world.storage_membership,
            actor=world.storage_user,
            warehouse_id=world.raw.pk,
            reference="Смешанный документ",
            effective_date=world.today,
            lines=[_sack_line(world, "10"), DraftLine(foreign.pk, world.packaging.pk, Decimal("5"), None, world.basis)],
        )
    assert OpeningBalance.objects.count() == 0
    assert StockLedgerEntry.objects.count() == 0


def test_flour_mass_must_match_bag_count(world):
    with pytest.raises(ValidationError):
        create_draft(
            membership=world.storage_membership,
            actor=world.storage_user,
            warehouse_id=world.finished.pk,
            reference="Неверная фасовка",
            effective_date=world.today,
            lines=[DraftLine(world.flour.pk, world.finished_location.pk, Decimal("400"), 10, world.basis)],
        )
    document = create_draft(
        membership=world.storage_membership,
        actor=world.storage_user,
        warehouse_id=world.finished.pk,
        reference="Сто мешков",
        effective_date=world.today,
        lines=[DraftLine(world.flour.pk, world.finished_location.pk, Decimal("500"), 10, world.basis)],
    )
    post_opening(membership=world.storage_membership, actor=world.storage_user, document_id=document.pk)
    entry = StockLedgerEntry.objects.get()
    assert entry.effect == StockLedgerEntry.Effect.OPENING
    assert entry.quantity == Decimal("500")
    assert entry.bags == 10


def test_opening_posts_once_and_blocks_catalogue_identity_changes(world):
    document = create_draft(
        membership=world.storage_membership,
        actor=world.storage_user,
        warehouse_id=world.raw.pk,
        reference="Мешки",
        effective_date=world.today,
        lines=[_sack_line(world)],
    )
    post_opening(membership=world.storage_membership, actor=world.storage_user, document_id=document.pk)
    post_opening(membership=world.storage_membership, actor=world.storage_user, document_id=document.pk)
    entry = StockLedgerEntry.objects.get(product=world.sack)
    assert entry.quantity == Decimal("500")
    assert AuditEvent.objects.filter(action=OPENING_COMMAND).count() == 1
    world.sack.grade = "тест"
    world.sack.save()
    world.sack.kind = Product.Kind.MATERIAL
    with pytest.raises(ValidationError):
        world.sack.save()


def test_reused_operation_key_with_other_data_posts_nothing(world):
    document = create_draft(
        membership=world.storage_membership,
        actor=world.storage_user,
        warehouse_id=world.raw.pk,
        reference="Ключ",
        effective_date=world.today,
        lines=[_sack_line(world, "3")],
    )
    OperationKey.objects.create(
        company=world.company,
        actor=world.storage_user,
        command=OPENING_COMMAND,
        key=document.key,
        fingerprint="0" * 64,
        result_label="conflict",
    )
    with pytest.raises(ValidationError):
        post_opening(membership=world.storage_membership, actor=world.storage_user, document_id=document.pk)
    document.refresh_from_db()
    assert document.state == OpeningBalance.State.DRAFT
    assert StockLedgerEntry.objects.count() == 0


def test_posted_facts_cannot_be_rewritten(world):
    document = create_draft(
        membership=world.storage_membership,
        actor=world.storage_user,
        warehouse_id=world.raw.pk,
        reference="Защита",
        effective_date=world.today,
        lines=[_sack_line(world, "4")],
    )
    post_opening(membership=world.storage_membership, actor=world.storage_user, document_id=document.pk)
    entry = StockLedgerEntry.objects.get()
    entry.quantity = Decimal("1")
    with pytest.raises(ValidationError):
        entry.save()
    line = document.lines.get()
    with pytest.raises(DatabaseError, match="не изменяется"):
        with transaction.atomic():
            StockLedgerEntry.objects.filter(pk=entry.pk).update(quantity=Decimal("1"))
    with pytest.raises(DatabaseError, match="не изменяются"):
        with transaction.atomic():
            OpeningLine.objects.filter(pk=line.pk).update(quantity=Decimal("1"))
    with pytest.raises(DatabaseError, match="не изменяется"):
        with transaction.atomic():
            OpeningBalance.objects.filter(pk=document.pk).update(reference="изменено")
    entry.refresh_from_db()
    assert entry.quantity == Decimal("4")


def test_customs_cannot_open_stock_and_storage_can(client, world):
    client.force_login(world.customs_user)
    denied = client.get(reverse("opening_create"))
    assert denied.status_code == 403
    client.force_login(world.storage_user)
    allowed = client.get(reverse("opening_create"))
    assert allowed.status_code == 200
    assert "Склад сырья" in allowed.content.decode()


def test_storage_user_signs_in_and_posts_opening_from_the_screen(client, world):
    login = client.post(reverse("login"), {"username": "storage", "password": "Demo-user-1"})
    assert login.status_code == 302
    home = client.get(login.url)
    page = home.content.decode()
    assert home.status_code == 200
    assert "Мариам-Ош" in page
    assert "Проведённых остатков пока нет." in page
    response = client.post(
        reverse("opening_create"),
        {
            "warehouse": world.raw.pk,
            "reference": "Проверка экрана",
            "effective_date": "2026-02-01",
            "lines-TOTAL_FORMS": "3",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "1",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-product": world.sack.pk,
            "lines-0-location": world.packaging.pk,
            "lines-0-quantity": "12",
            "lines-0-bags": "",
            "lines-0-basis": world.basis,
            "lines-1-product": "",
            "lines-1-location": "",
            "lines-1-quantity": "",
            "lines-1-bags": "",
            "lines-1-basis": "",
            "lines-2-product": "",
            "lines-2-location": "",
            "lines-2-quantity": "",
            "lines-2-bags": "",
            "lines-2-basis": "",
        },
    )
    assert response.status_code == 302, response.content.decode()
    detail = client.get(response.url)
    assert "Черновик" in detail.content.decode()
    pk = response.url.rstrip("/").split("/")[-1]
    posted = client.post(reverse("opening_post", args=[pk]))
    assert posted.status_code == 302
    balance = client.get(reverse("balance_list"))
    assert "12" in balance.content.decode()


def test_seed_is_idempotent_and_admin_lists_the_catalogue(client):
    call_command("seed_demo")
    call_command("seed_demo")
    sack = StockLedgerEntry.objects.get(product__sku="SACK-50")
    wheat = StockLedgerEntry.objects.get(product__sku="WHEAT-4")
    assert sack.quantity == Decimal("500")
    assert wheat.quantity == Decimal("8000")
    assert StockLedgerEntry.objects.filter(product__sku="SACK-50").count() == 1
    assert not StockLedgerEntry.objects.filter(product__sku="BRAN-KG").exists()
    assert AuditEvent.objects.filter(action=OPENING_COMMAND).count() == 1
    assert Warehouse.objects.filter(company__code="mariam-osh").count() == 2
    assert User.objects.get(username="storage").check_password(DEMO_PASSWORDS["storage"])
    client.force_login(User.objects.get(username="admin"))
    page = client.get("/admin/")
    assert page.status_code == 200
    body = page.content.decode()
    assert "Товары" in body
    assert "Предприятия" in body
