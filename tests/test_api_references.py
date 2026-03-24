"""Route-level validation tests for references support."""
import asyncio
import json
import unittest
from types import SimpleNamespace

from src.api import routes
from src.core.models import ChatCompletionRequest, ChatMessage


class _RejectingReferenceService:
    async def validate_reference_ids(self, reference_ids):
        raise ValueError("reference s2ref_missing not found")


class _AcceptingReferenceService:
    async def validate_reference_ids(self, reference_ids):
        return []


class ReferenceApiValidationTests(unittest.TestCase):
    def tearDown(self):
        routes.set_generation_handler(None)

    def test_references_are_rejected_for_image_models(self):
        async def scenario():
            routes.set_generation_handler(SimpleNamespace(reference_service=_AcceptingReferenceService()))
            request = ChatCompletionRequest(
                model="gpt-image",
                messages=[ChatMessage(role="user", content="test")],
                references=["s2ref_123"],
                stream=False,
            )
            response = await routes.create_chat_completion(
                request=request,
                api_key="test",
                http_request=SimpleNamespace(headers={}),
            )
            return response

        response = asyncio.run(scenario())
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            payload["error"]["message"],
            "references are only supported for standard video and storyboard generation",
        )

    def test_unknown_reference_id_returns_400(self):
        async def scenario():
            routes.set_generation_handler(SimpleNamespace(reference_service=_RejectingReferenceService()))
            request = ChatCompletionRequest(
                model="sora2-landscape-10s",
                messages=[ChatMessage(role="user", content="test")],
                references=["s2ref_missing"],
                stream=False,
            )
            response = await routes.create_chat_completion(
                request=request,
                api_key="test",
                http_request=SimpleNamespace(headers={}),
            )
            return response

        response = asyncio.run(scenario())
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["message"], "reference s2ref_missing not found")


if __name__ == "__main__":
    unittest.main()
