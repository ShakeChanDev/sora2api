"""Tests for the platform-local reference library and token sync."""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from src.core.database import Database
from src.core.models import Token
from src.core.secret_codec import secret_codec
from src.services.reference_service import ReferenceService


class _FakeSoraClient:
    def __init__(self):
        self.upload_calls = []
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []
        self.upstream_items = []

    async def upload_reference_image(self, image_data, token, filename, token_id=None):
        self.upload_calls.append(
            {
                "size": len(image_data),
                "token": token,
                "filename": filename,
                "token_id": token_id,
            }
        )
        return f"sediment://asset_{len(self.upload_calls)}"

    async def get_references(self, token, limit=20, token_id=None):
        return {"items": list(self.upstream_items)}

    async def create_reference(self, token, name, description, reference_type, asset_pointers=None, token_id=None):
        upstream_reference_id = f"ref_created_{len(self.create_calls) + 1}"
        self.create_calls.append(
            {
                "token": token,
                "name": name,
                "description": description,
                "type": reference_type,
                "asset_pointers": asset_pointers,
                "token_id": token_id,
                "upstream_reference_id": upstream_reference_id,
            }
        )
        self.upstream_items.append({"reference_id": upstream_reference_id})
        return {"reference_info": {"reference_id": upstream_reference_id}}

    async def update_reference(self, token, upstream_reference_id, name, description, reference_type, asset_pointers=None, token_id=None):
        self.update_calls.append(
            {
                "token": token,
                "upstream_reference_id": upstream_reference_id,
                "name": name,
                "description": description,
                "type": reference_type,
                "asset_pointers": asset_pointers,
                "token_id": token_id,
            }
        )
        return {"reference_info": {"reference_id": upstream_reference_id}}

    async def delete_reference(self, upstream_reference_id, token, token_id=None):
        self.delete_calls.append(
            {
                "upstream_reference_id": upstream_reference_id,
                "token": token,
                "token_id": token_id,
            }
        )
        return True


class ReferenceServiceTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.assets_dir = Path(tempfile.mkdtemp(prefix="reference-assets-"))
        secret_codec.configure("unit-test-secret")
        self.db = Database(self.db_path)
        asyncio.run(self.db.init_db({}))
        self.sora_client = _FakeSoraClient()
        self.service = ReferenceService(self.db, self.sora_client, assets_dir=self.assets_dir)

    def tearDown(self):
        secret_codec.configure("")
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        if self.assets_dir.exists():
            for child in sorted(self.assets_dir.glob("**/*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            self.assets_dir.rmdir()

    def test_create_reference_persists_asset_and_preview_url(self):
        async def scenario():
            result = await self.service.create_reference(
                name="衣服",
                description="黑色衣服",
                reference_type="setting",
                image_bytes=b"fake-image-data",
                filename="cloth.png",
            )
            stored = await self.db.get_reference(result["reference_id"])
            return result, stored

        result, stored = asyncio.run(scenario())
        self.assertTrue(result["reference_id"].startswith("s2ref_"))
        self.assertEqual(result["type"], "setting")
        self.assertTrue(result["preview_url"].startswith("/reference-assets/"))
        self.assertIsNotNone(stored)
        self.assertTrue((self.assets_dir / stored.asset_path).exists())
        self.assertEqual(stored.name, "衣服")

    def test_resolve_references_creates_updates_and_recreates_binding(self):
        async def scenario():
            reference = await self.service.create_reference(
                name="角色图",
                description="初始描述",
                reference_type="character",
                image_bytes=b"reference-image",
                filename="character.webp",
            )
            token_id = await self.db.add_token(Token(token="tok", email="user@example.com", name="User"))

            first_ids = await self.service.resolve_references_for_token([reference["reference_id"]], token_id, "tok")
            binding_after_create = await self.db.get_reference_binding(reference["reference_id"], token_id)

            await self.service.update_reference(
                reference_id=reference["reference_id"],
                description="更新后的描述",
            )
            second_ids = await self.service.resolve_references_for_token([reference["reference_id"]], token_id, "tok")

            self.sora_client.upstream_items = []
            third_ids = await self.service.resolve_references_for_token([reference["reference_id"]], token_id, "tok")
            binding_after_recreate = await self.db.get_reference_binding(reference["reference_id"], token_id)

            await self.service.delete_reference(reference["reference_id"])
            deleted_reference = await self.db.get_reference(reference["reference_id"])
            deleted_binding = await self.db.get_reference_binding(reference["reference_id"], token_id)

            return (
                first_ids,
                second_ids,
                third_ids,
                binding_after_create,
                binding_after_recreate,
                deleted_reference,
                deleted_binding,
            )

        (
            first_ids,
            second_ids,
            third_ids,
            binding_after_create,
            binding_after_recreate,
            deleted_reference,
            deleted_binding,
        ) = asyncio.run(scenario())

        self.assertEqual(len(first_ids), 1)
        self.assertEqual(len(self.sora_client.create_calls), 2)
        self.assertEqual(len(self.sora_client.update_calls), 1)
        self.assertEqual(self.sora_client.update_calls[0]["asset_pointers"], None)
        self.assertEqual(binding_after_create.upstream_reference_id, first_ids[0])
        self.assertEqual(second_ids[0], first_ids[0])
        self.assertNotEqual(third_ids[0], first_ids[0])
        self.assertEqual(binding_after_recreate.upstream_reference_id, third_ids[0])
        self.assertEqual(len(self.sora_client.delete_calls), 1)
        self.assertIsNone(deleted_reference)
        self.assertIsNone(deleted_binding)


if __name__ == "__main__":
    unittest.main()
