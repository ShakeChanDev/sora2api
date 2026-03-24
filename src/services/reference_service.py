"""Reference master library and per-token upstream sync."""
import hashlib
import json
import shutil
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from ..core.database import Database
from ..core.logger import debug_logger
from ..core.models import ReferenceBinding, ReferenceRecord
from .sora_client import SoraClient


class ReferenceService:
    """Manage local references and sync them to the selected upstream account."""

    ALLOWED_TYPES = {"character", "setting", "style", "other"}
    MAX_REFERENCES = 5
    REFERENCE_UPLOAD_STRATEGY = "inpaint_safe_v1"

    def __init__(
        self,
        db: Database,
        sora_client: SoraClient,
        assets_dir: Optional[Path] = None,
        public_mount: str = "/reference-assets",
    ):
        self.db = db
        self.sora_client = sora_client
        self.assets_dir = assets_dir or (Path(__file__).parent.parent.parent / "data" / "reference_assets")
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.public_mount = public_mount.rstrip("/")

    def _normalize_name(self, value: Optional[str]) -> str:
        name = (value or "").strip()
        if not name:
            raise ValueError("reference name is required")
        return name

    def _normalize_description(self, value: Optional[str]) -> Optional[str]:
        description = (value or "").strip()
        return description or None

    def _normalize_type(self, value: Optional[str]) -> str:
        reference_type = (value or "other").strip().lower()
        if reference_type not in self.ALLOWED_TYPES:
            raise ValueError("reference type must be one of character, setting, style, other")
        return reference_type

    def _asset_directory(self, reference_id: str) -> Path:
        return self.assets_dir / reference_id

    def _asset_absolute_path(self, asset_path: str) -> Path:
        return self.assets_dir / Path(asset_path)

    def _guess_extension(self, filename: Optional[str]) -> str:
        suffix = Path(filename or "").suffix.lower()
        return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"} else ".png"

    def _build_preview_url(self, asset_path: str) -> str:
        return f"{self.public_mount}/{asset_path.replace(chr(92), '/')}"

    def _serialize_reference(self, reference: ReferenceRecord) -> dict:
        return {
            "reference_id": reference.reference_id,
            "name": reference.name,
            "description": reference.description,
            "type": reference.type,
            "preview_url": self._build_preview_url(reference.asset_path),
            "created_at": reference.created_at.isoformat() if reference.created_at else None,
            "updated_at": reference.updated_at.isoformat() if reference.updated_at else None,
        }

    def _build_sync_fingerprint_payload(self, reference: ReferenceRecord) -> dict:
        return {
            "name": reference.name,
            "description": reference.description,
            "type": reference.type,
            "asset_hash": reference.asset_hash,
            "upload_strategy": self.REFERENCE_UPLOAD_STRATEGY,
        }

    def _build_sync_fingerprint(self, reference: ReferenceRecord) -> str:
        return json.dumps(self._build_sync_fingerprint_payload(reference), ensure_ascii=False, sort_keys=True)

    def _parse_sync_fingerprint(self, value: Optional[str]) -> dict:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _persist_asset(self, reference_id: str, image_bytes: bytes, filename: Optional[str]) -> tuple[str, str]:
        extension = self._guess_extension(filename)
        asset_dir = self._asset_directory(reference_id)
        if asset_dir.exists():
            shutil.rmtree(asset_dir)
        asset_dir.mkdir(parents=True, exist_ok=True)

        asset_name = f"source{extension}"
        asset_path = asset_dir / asset_name
        asset_path.write_bytes(image_bytes)
        asset_hash = hashlib.sha256(image_bytes).hexdigest()
        return f"{reference_id}/{asset_name}", asset_hash

    def _delete_local_assets(self, reference_id: str):
        asset_dir = self._asset_directory(reference_id)
        if asset_dir.exists():
            shutil.rmtree(asset_dir)

    def _extract_upstream_reference_id(self, payload: dict) -> str:
        candidates = [
            payload.get("reference_id"),
            payload.get("reference", {}).get("reference_id") if isinstance(payload.get("reference"), dict) else None,
            payload.get("reference_info", {}).get("reference_id") if isinstance(payload.get("reference_info"), dict) else None,
        ]
        for candidate in candidates:
            if candidate:
                return candidate
        raise Exception("upstream reference create did not return reference_id")

    async def _load_reference_image(self, reference: ReferenceRecord) -> tuple[bytes, str]:
        asset_path = self._asset_absolute_path(reference.asset_path)
        if not asset_path.exists():
            raise ValueError(f"reference asset missing for {reference.reference_id}")
        return asset_path.read_bytes(), asset_path.name

    async def _upload_local_reference_asset(self, reference: ReferenceRecord, token: str, token_id: int) -> str:
        image_bytes, filename = await self._load_reference_image(reference)
        asset_pointer = await self.sora_client.upload_reference_image(
            image_bytes,
            token=token,
            filename=filename,
            token_id=token_id,
        )
        if not asset_pointer:
            raise Exception("reference asset upload did not return asset_pointer")
        return asset_pointer

    async def _create_upstream_reference(self, reference: ReferenceRecord, token: str, token_id: int) -> str:
        asset_pointer = await self._upload_local_reference_asset(reference, token, token_id)
        response = await self.sora_client.create_reference(
            token=token,
            name=reference.name,
            description=reference.description,
            reference_type=reference.type,
            asset_pointers=[asset_pointer],
            token_id=token_id,
        )
        return self._extract_upstream_reference_id(response)

    async def _update_upstream_reference(
        self,
        reference: ReferenceRecord,
        binding: ReferenceBinding,
        token: str,
        token_id: int,
    ):
        previous_payload = self._parse_sync_fingerprint(binding.sync_fingerprint)
        asset_changed = (
            previous_payload.get("asset_hash") != reference.asset_hash
            or previous_payload.get("upload_strategy") != self.REFERENCE_UPLOAD_STRATEGY
        )
        asset_pointers = None
        if asset_changed:
            asset_pointers = [await self._upload_local_reference_asset(reference, token, token_id)]
        await self.sora_client.update_reference(
            token=token,
            upstream_reference_id=binding.upstream_reference_id,
            name=reference.name,
            description=reference.description,
            reference_type=reference.type,
            asset_pointers=asset_pointers,
            token_id=token_id,
        )

    async def list_references(self) -> List[dict]:
        """List local references for admin clients."""
        references = await self.db.list_references()
        return [self._serialize_reference(reference) for reference in references]

    async def get_reference(self, reference_id: str) -> dict:
        """Get a single local reference."""
        reference = await self.db.get_reference(reference_id)
        if not reference:
            raise ValueError(f"reference {reference_id} not found")
        return self._serialize_reference(reference)

    async def create_reference(
        self,
        name: Optional[str],
        description: Optional[str],
        reference_type: Optional[str],
        image_bytes: bytes,
        filename: Optional[str],
    ) -> dict:
        """Create a local reference record and persist its source image."""
        if not image_bytes:
            raise ValueError("reference image is required")

        reference_id = f"s2ref_{uuid4().hex}"
        asset_path, asset_hash = self._persist_asset(reference_id, image_bytes, filename)
        reference = ReferenceRecord(
            reference_id=reference_id,
            name=self._normalize_name(name),
            description=self._normalize_description(description),
            type=self._normalize_type(reference_type),
            asset_path=asset_path,
            asset_hash=asset_hash,
        )
        await self.db.create_reference(reference)
        saved = await self.db.get_reference(reference_id)
        return self._serialize_reference(saved or reference)

    async def update_reference(
        self,
        reference_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        reference_type: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        filename: Optional[str] = None,
    ) -> dict:
        """Update a local reference and optionally replace its source image."""
        current = await self.db.get_reference(reference_id)
        if not current:
            raise ValueError(f"reference {reference_id} not found")

        next_name = current.name if name is None else self._normalize_name(name)
        next_description = current.description if description is None else self._normalize_description(description)
        next_type = current.type if reference_type is None else self._normalize_type(reference_type)
        next_asset_path = current.asset_path
        next_asset_hash = current.asset_hash

        if image_bytes is not None:
            next_asset_path, next_asset_hash = self._persist_asset(reference_id, image_bytes, filename)

        await self.db.update_reference(
            reference_id=reference_id,
            name=next_name,
            description=next_description,
            type=next_type,
            asset_path=next_asset_path,
            asset_hash=next_asset_hash,
        )
        updated = await self.db.get_reference(reference_id)
        return self._serialize_reference(updated or current)

    async def delete_reference(self, reference_id: str):
        """Delete a local reference and best-effort clean upstream bindings."""
        reference = await self.db.get_reference(reference_id)
        if not reference:
            raise ValueError(f"reference {reference_id} not found")

        bindings = await self.db.list_reference_bindings(reference_id=reference_id)
        for binding in bindings:
            try:
                token = await self.db.get_token(binding.token_id)
                if token and token.token:
                    await self.sora_client.delete_reference(
                        upstream_reference_id=binding.upstream_reference_id,
                        token=token.token,
                        token_id=token.id,
                    )
            except Exception as exc:
                debug_logger.log_warning(
                    f"Failed to delete upstream reference {binding.upstream_reference_id} for token {binding.token_id}: {exc}"
                )

        await self.db.delete_reference(reference_id)
        self._delete_local_assets(reference_id)

    async def validate_reference_ids(self, reference_ids: Optional[List[str]]) -> List[ReferenceRecord]:
        """Validate caller-provided local reference ids."""
        if reference_ids is None:
            return []
        if not isinstance(reference_ids, list):
            raise ValueError("references must be an array of strings")

        deduped_ids: List[str] = []
        seen = set()
        for item in reference_ids:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("references must be an array of strings")
            reference_id = item.strip()
            if reference_id not in seen:
                seen.add(reference_id)
                deduped_ids.append(reference_id)

        if len(deduped_ids) > self.MAX_REFERENCES:
            raise ValueError("references supports at most 5 unique ids")

        references: List[ReferenceRecord] = []
        for reference_id in deduped_ids:
            reference = await self.db.get_reference(reference_id)
            if not reference:
                raise ValueError(f"reference {reference_id} not found")
            references.append(reference)
        return references

    async def resolve_references_for_token(
        self,
        reference_ids: Optional[List[str]],
        token_id: int,
        token: str,
    ) -> List[str]:
        """Resolve local reference ids into upstream reference ids for the selected token."""
        references = await self.validate_reference_ids(reference_ids)
        if not references:
            return []

        upstream_payload = await self.sora_client.get_references(token=token, limit=100, token_id=token_id)
        upstream_items = upstream_payload.get("items", []) if isinstance(upstream_payload, dict) else []
        upstream_reference_ids = {
            item.get("reference_id")
            for item in upstream_items
            if isinstance(item, dict) and item.get("reference_id")
        }

        resolved_reference_ids: List[str] = []
        for reference in references:
            binding = await self.db.get_reference_binding(reference.reference_id, token_id)
            fingerprint = self._build_sync_fingerprint(reference)

            if binding and binding.sync_fingerprint == fingerprint and binding.upstream_reference_id in upstream_reference_ids:
                resolved_reference_ids.append(binding.upstream_reference_id)
                continue

            if binding and binding.upstream_reference_id in upstream_reference_ids:
                try:
                    await self._update_upstream_reference(reference, binding, token, token_id)
                    await self.db.upsert_reference_binding(
                        ReferenceBinding(
                            reference_id=reference.reference_id,
                            token_id=token_id,
                            upstream_reference_id=binding.upstream_reference_id,
                            sync_fingerprint=fingerprint,
                        )
                    )
                    resolved_reference_ids.append(binding.upstream_reference_id)
                    continue
                except Exception as exc:
                    if "404" not in str(exc):
                        raise
                    debug_logger.log_warning(
                        f"Upstream reference {binding.upstream_reference_id} missing for token {token_id}, recreating: {exc}"
                    )
                    await self.db.delete_reference_binding(reference.reference_id, token_id)

            upstream_reference_id = await self._create_upstream_reference(reference, token, token_id)
            await self.db.upsert_reference_binding(
                ReferenceBinding(
                    reference_id=reference.reference_id,
                    token_id=token_id,
                    upstream_reference_id=upstream_reference_id,
                    sync_fingerprint=fingerprint,
                )
            )
            upstream_reference_ids.add(upstream_reference_id)
            resolved_reference_ids.append(upstream_reference_id)

        return resolved_reference_ids
