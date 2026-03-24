"""Tests for reference payload wiring in MutationExecutor."""
import asyncio
import unittest
from types import SimpleNamespace

from src.services.mutation_executor import MutationExecutor


class MutationExecutorReferenceTests(unittest.TestCase):
    def test_video_submit_merges_upload_and_reference_items(self):
        async def scenario():
            captured = {}
            executor = MutationExecutor(db=SimpleNamespace(), provider=None, runtime=SimpleNamespace(), proxy_manager=None)

            async def fake_ensure(_token_id):
                return None

            async def fake_run_page_plan(*, mutation_type, token_id, request_plan):
                captured["mutation_type"] = mutation_type
                captured["token_id"] = token_id
                captured["payload"] = request_plan[0].json_body
                return SimpleNamespace(task_id="task_1")

            executor.ensure_video_token_binding = fake_ensure
            executor._run_page_plan = fake_run_page_plan

            await executor.execute_video_submit(
                prompt="test prompt",
                token_id=7,
                orientation="portrait",
                n_frames=300,
                model="sy_8",
                size="small",
                media_id="upload_1",
                style_id=None,
                reference_ids=["ref_1", "ref_2"],
            )
            return captured

        captured = asyncio.run(scenario())
        self.assertEqual(captured["token_id"], 7)
        self.assertEqual(
            captured["payload"]["inpaint_items"],
            [
                {"kind": "upload", "upload_id": "upload_1"},
                {"kind": "reference", "reference_id": "ref_1"},
                {"kind": "reference", "reference_id": "ref_2"},
            ],
        )
        self.assertIn("use_image_as_first_frame", captured["payload"])
        self.assertIn("i2v_reference_instruction", captured["payload"])


if __name__ == "__main__":
    unittest.main()
