import unittest

from polo_adapter.app.errors import AdapterError
from polo_adapter.app.mappers import ModelMetadata, ensure_references_supported


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


if __name__ == "__main__":
    unittest.main()
