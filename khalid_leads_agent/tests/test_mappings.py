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
    lead = OdooLead(id=1, source="Meta", medium="Leads")
    assert odoo_source_labels(lead)[0] == "Meta / Leads"
    res = m.resolve_source(lead)
    assert not res.mapped and res.odoo_value == "Meta / Leads"  # never guessed
    m.save_source("Meta", "Meta || Leads (generic)")
    assert m.resolve_source(lead).sheet_value == "Meta || Leads (generic)"
    m.save_source("Meta / Leads", "Meta || Leads")  # more specific wins
    res = m.resolve_source(lead)
    assert res.mapped and res.sheet_value == "Meta || Leads" and res.odoo_value == "Meta / Leads"


def test_source_mapping_other_source(container):
    container.mappings.save_source("Twajd", "تيك توك")
    assert container.mappings.resolve_source(OdooLead(id=2, source="twajd")).sheet_value == "تيك توك"
    assert not container.mappings.resolve_source(OdooLead(id=3, source="LinkedIn")).mapped
    assert not container.mappings.resolve_source(None).mapped


def test_source_mapping_validation(container):
    with pytest.raises(AgentError):
        container.mappings.save_source("", "x")
