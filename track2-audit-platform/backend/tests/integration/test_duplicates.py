"""Integration tests for duplicate classification and evidence generation."""

from app.engines.identity.resolver import DuplicateResolver


class TestDuplicateResolverIntegration:
    def test_typo_matches_as_candidate(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "John Doe", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Jon Doe", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})

        results = resolver.resolve("r1", {"payee_name": "John Doe", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "CANDIDATE" for item in results)
        assert results[0].evidence.algorithm_version == "p06-levenshtein-v1"

    def test_reversal_is_non_match(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Alice Smith", "amount_minor": -1000, "sender_account_id": "B1", "receiver_account_id": "A1"})

        results = resolver.resolve("r1", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "NON_MATCH" for item in results)

    def test_positive_and_negative_fixtures(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.8,
        )
        resolver.add_record("r1", {"payee_name": "Alpha Corp", "amount_minor": 10000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Alpha Corp", "amount_minor": 10000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r3", {"payee_name": "Gamma Ltd", "amount_minor": 20000, "sender_account_id": "A2", "receiver_account_id": "B2"})

        results = resolver.resolve("r1", {"payee_name": "Alpha Corp", "amount_minor": 10000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "EXACT" for item in results)
        assert all(item.record_id_b != "r3" or item.result == "NON_MATCH" for item in results)

    def test_bucket_skew_and_performance_tradeoff(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.7,
        )
        for idx in range(50):
            resolver.add_record(f"r{idx}", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})

        results = resolver.resolve("r0", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert len(results) >= 1
        assert all(item.evidence.candidate_record_ids[0] == "r0" for item in results)
