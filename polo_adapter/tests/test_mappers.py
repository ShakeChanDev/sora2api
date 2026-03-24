import unittest
from datetime import datetime

from polo_adapter.app.errors import AdapterError
from polo_adapter.app.mappers import (
    ModelMetadata,
    ensure_references_supported,
    parse_completed_timestamp,
    parse_created_timestamp,
)


class MapperTests(unittest.TestCase):
    def test_references_support_guard_rejects_unsupported_models(self):
        with self.assertRaises(AdapterError) as ctx:
            ensure_references_supported(
                ModelMetadata(
                    external_name="synthetic",
                    internal_name="synthetic",
                    references_supported=False,
                )
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "references_not_supported")

    def test_parse_created_timestamp_treats_naive_values_as_utc(self):
        expected = int(datetime.fromisoformat("2026-03-24 12:00:00+00:00").timestamp())
        self.assertEqual(parse_created_timestamp("2026-03-24 12:00:00"), expected)

    def test_parse_completed_timestamp_uses_configured_local_timezone(self):
        expected = int(datetime.fromisoformat("2026-03-24 12:00:00+08:00").timestamp())
        self.assertEqual(parse_completed_timestamp("2026-03-24 12:00:00", "Asia/Shanghai"), expected)


if __name__ == "__main__":
    unittest.main()
