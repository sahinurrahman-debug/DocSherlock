"""LOW_MEMORY is the one-switch preset for 512 MB hosts."""
from app.core.config import Settings


def test_low_memory_preset_turns_heavy_features_down():
    s = Settings(low_memory=True, database_url="", dense_enabled=True, rerank_enabled=True, ocr_max_side=2600, ingest_workers=4)
    assert not s.dense_enabled and not s.rerank_enabled
    assert s.ocr_max_side <= 1100 and s.ocr_render_dpi <= 130 and s.ocr_threads == 1 and s.ingest_workers == 1


def test_flag_off_leaves_settings_untouched():
    s = Settings(low_memory=False, database_url="", dense_enabled=True, rerank_enabled=True, ocr_max_side=2600, ingest_workers=4)
    assert s.dense_enabled and s.rerank_enabled and s.ocr_max_side == 2600 and s.ingest_workers == 4


def test_retention_purge_removes_only_old_documents(api):
    from datetime import datetime, timedelta, timezone

    from app.core.database import SessionLocal
    from app.models.document import Document
    from app.services import ingestion

    old = api.add_text("old.txt", "Invoices are payable Net 30 from the invoice date.")
    api.add_text("new.txt", "Employees receive 20 days of paid annual leave per year.")
    with SessionLocal() as db:
        db.get(Document, old["id"]).uploaded_at = datetime.now(timezone.utc) - timedelta(days=30)
        db.commit()
    assert ingestion.purge_old_documents(0) == 0                      # disabled by default
    assert ingestion.purge_old_documents(14) >= 1
    assert [d["filename"] for d in api.docs()] == ["new.txt"]
