"""Moving the Odoo lead to a stage when a result is saved (optional mapping)."""
from tests.test_results import prepare, save


def _setup(container, **extra):
    container.settings.update({"odoo_stage_by_result": {"INTERESTED": "Qualified", "NO_ANSWER": "جديد",
                                                       "SUBSCRIBED": "Won"}, "duplicate_window_seconds": 0, **extra})
    return prepare(container)


def test_off_by_default(container, odoo):
    lead = prepare(container)
    res = save(container, idempotency_key="stage-off-1", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert res["status"] == "done" and odoo.stage_writes == [] and "odoo_stage" not in res["preview"]


def test_mapped_result_moves_the_lead_forward(container, odoo):
    lead = _setup(container)
    res = save(container, idempotency_key="stage-int-1", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert odoo.stage_writes == [{"id": 1, "stage_id": 2}] and odoo.leads[1].stage == "Qualified"
    assert res["preview"]["odoo_stage"]["status"] == "success" and res["status"] == "done"
    # Same stage again: nothing written.
    res = save(container, idempotency_key="stage-int-2", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert res["preview"]["odoo_stage"]["status"] == "nochange" and len(odoo.stage_writes) == 1


def test_never_moves_back_or_out_of_won(container, odoo):
    lead = _setup(container)
    odoo.leads[1].stage = "Proposition"
    res = save(container, idempotency_key="stage-back-1", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert res["preview"]["odoo_stage"]["status"] == "nochange" and odoo.stage_writes == []
    assert "قبل المرحلة الحالية" in res["preview"]["odoo_stage"]["message"]
    container.settings.update({"odoo_stage_no_back": False})
    save(container, idempotency_key="stage-back-2", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert odoo.leads[1].stage == "Qualified"  # allowed when the option is off
    odoo.leads[1].stage = "Won"
    res = save(container, idempotency_key="stage-won-1", fingerprint=lead["fingerprint"], result_code="NO_ANSWER")
    assert res["preview"]["odoo_stage"]["status"] == "nochange" and odoo.leads[1].stage == "Won"


def test_dry_run_and_unknown_stage(container, odoo):
    lead = _setup(container, dry_run=True)
    res = save(container, idempotency_key="stage-dry-1", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert res["preview"]["odoo_stage"]["status"] == "dry_run" and odoo.stage_writes == []
    container.settings.update({"dry_run": False, "odoo_stage_by_result": {"INTERESTED": "مرحلة محذوفة"}})
    res = save(container, idempotency_key="stage-unk-1", fingerprint=lead["fingerprint"], result_code="INTERESTED")
    assert res["status"] == "done"  # a stage problem never blocks the save
    assert res["preview"]["odoo_stage"]["status"] == "failed"
    assert any("لم تتغير مرحلة العميل" in w for w in res["warnings"])


def test_stages_endpoint(container):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(container, allowed_hosts=["testserver"])) as tc:
        names = [s["name"] for s in tc.get("/api/odoo/stages").json()["stages"]]
        assert names == ["جديد", "Qualified", "Proposition", "Won"]
