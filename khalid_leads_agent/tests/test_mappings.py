import pytest

from app.adapters.odoo.base import OdooLead
from app.errors import AgentError
from app.services.mapping_service import odoo_source_labels, source_key


def test_status_mapping_defaults_and_update(container):
    m = container.mappings
    assert m.status_sheet_value("NO_ANSWER") == "لم يتم الرد"
    assert m.status_sheet_value("INVALID_NUMBER") == "بيانات التواصل غير صحيحة"
    m.save_statuses([{"code": "INVALID_NUMBER", "label": "رقم غير صحيح", "sheet_value": "رقم خاطئ"}])
    assert m.status_sheet_value("INVALID_NUMBER") == "رقم خاطئ"


def test_status_mapping_unmapped_is_blocked(container):
    container.mappings.save_statuses([{"code": "SUBSCRIBED", "label": "تم الاشتراك", "sheet_value": ""}])
    with pytest.raises(AgentError) as exc:
        container.mappings.status_sheet_value("SUBSCRIBED")
    assert exc.value.code == "STATUS_NOT_MAPPED"
    with pytest.raises(AgentError):
        container.mappings.status_sheet_value("UNKNOWN")


def test_source_key_normalization():
    assert source_key("Meta/Leads") == source_key("meta / leads") == source_key(" Meta || Leads ")


def test_source_mapping_resolution_priority(container):
    m = container.mappings
    lead = OdooLead(id=1, source="Meta", medium="Leads", utm_source="Meta / Leads")
    assert odoo_source_labels(lead) == ["Meta / Leads"]  # UTM Source only
    m.source_options = None
    res = m.resolve_source(lead)
    assert not res.mapped and res.odoo_value == "Meta / Leads"  # no mapping and no sheet options: never guessed
    m.source_options = lambda: ["Meta || Leads", "تيك توك", "باور بي اي"]
    res = m.resolve_source(lead)  # identical sheet value after normalization ("/" == "||")
    assert res.mapped and res.auto and res.sheet_value == "Meta || Leads" and res.odoo_value == "Meta / Leads"
    assert not m.resolve_source(OdooLead(id=5, utm_source="Snapchat")).mapped  # nothing fuzzy
    m.source_options = lambda: ["Meta || Leads", "meta | leads"]  # ambiguous → user picks
    assert not m.resolve_source(lead).mapped
    m.source_options = None
    m.save_source("Meta / Leads", "Meta || Leads (generic)")  # a saved mapping wins
    res = m.resolve_source(lead)
    assert res.mapped and res.sheet_value == "Meta || Leads (generic)" and not res.auto


def test_source_mapping_uses_utm_source_not_source(container):
    m = container.mappings
    m.source_options = lambda: ["Meta || Leads", "رصد لاندنج"]
    m.save_source("Rassd Landing", "رصد لاندنج")
    # Source (source_id) says Meta, UTM Source says Rassd Landing → the sheet gets the UTM Source mapping.
    res = m.resolve_source(OdooLead(id=1, source="Meta", medium="Leads", utm_source="Rassd Landing"))
    assert res.mapped and res.sheet_value == "رصد لاندنج" and res.odoo_value == "Rassd Landing"
    # No UTM Source → nothing, even when Source alone would match.
    assert not m.resolve_source(OdooLead(id=2, source="Meta / Leads")).mapped
    assert odoo_source_labels(OdooLead(id=3, source="Meta")) == []


def test_source_mapping_other_source(container):
    container.mappings.save_source("Twajd", "تيك توك")
    assert container.mappings.resolve_source(OdooLead(id=2, utm_source="twajd")).sheet_value == "تيك توك"
    assert not container.mappings.resolve_source(OdooLead(id=3, utm_source="LinkedIn")).mapped
    assert not container.mappings.resolve_source(None).mapped


def test_source_mapping_validation(container):
    with pytest.raises(AgentError):
        container.mappings.save_source("", "x")
