"""A shared Storage keeps one transaction context per exact tenant key."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time

import pytest

from retrieval.storage import Storage


def test_concurrent_first_use_reuses_one_repository(monkeypatch, tmp_path):
    created = []
    start = Barrier(8)

    class Repository:
        def __init__(self, tenant):
            time.sleep(0.03)  # Allow competing first reads to enter the cache.
            self.tenant = tenant
            created.append(self)

    monkeypatch.setattr('service.postgres_business_documents.PostgresBusinessDocuments', Repository)
    storage = Storage('ALPHA', base_dir=tmp_path)

    def first_read(_index):
        start.wait(timeout=5)
        return storage._postgres_repository('ALPHA')

    with ThreadPoolExecutor(max_workers=8) as workers:
        repositories = list(workers.map(first_read, range(8)))
    assert len(created) == 1
    assert all(repository is created[0] for repository in repositories)
    assert storage._postgres_repository() is created[0]


def test_repository_cache_preserves_exact_tenant_boundaries(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr('service.postgres_business_documents.PostgresBusinessDocuments',
                        lambda tenant: SimpleNamespace(tenant=tenant))
    storage = Storage('ALPHA', base_dir=tmp_path)
    upper = storage._postgres_repository('ALPHA')
    lower = storage._postgres_repository('Alpha')
    assert upper is not lower
    assert upper.tenant == 'ALPHA' and lower.tenant == 'Alpha'
    with pytest.raises(ValueError, match='invalid_tenant'):
        storage._postgres_repository('../ALPHA')
