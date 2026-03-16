"""Strategy-based high-risk mutation executor."""
from typing import Any, Awaitable, Callable, Dict, Optional

from ..core.database import Database
from ..core.models import Token
from .auth_context_service import browser_session
from .browser_provider import BrowserProvider
from .browser_runtime import (
    BrowserLockManager,
    MutationExecutionResult,
    append_attempt,
    classify_high_risk_failure,
    extract_upstream_error,
    safe_json_dumps,
)

ReplayCallable = Callable[[Any], Awaitable[Any]]
PageCallable = Callable[[Any], Awaitable[Any]]


class MutationExecutor:
    """Execute high-risk mutations with replay/page strategies."""

    DEFAULT_STRATEGIES: Dict[str, str] = {
        "image_upload": "replay_http",
        "image_submit": "replay_then_page_fallback",
        "video_submit": "replay_then_page_fallback",
        "storyboard_submit": "replay_then_page_fallback",
        "remix_submit": "replay_then_page_fallback",
        "long_video_extension": "replay_then_page_fallback",
        "publish_execute": "page_execute",
    }

    def __init__(self, provider: BrowserProvider, db: Database, lock_manager: Optional[BrowserLockManager] = None):
        self.provider = provider
        self.db = db
        self.lock_manager = lock_manager or BrowserLockManager()

    async def execute(
        self,
        token: Token,
        *,
        mutation_type: str,
        target_url: str,
        replay_callable: Optional[ReplayCallable] = None,
        page_callable: Optional[PageCallable] = None,
        task_id: Optional[str] = None,
        close_on_exit: bool = True,
    ) -> MutationExecutionResult:
        strategy = self.DEFAULT_STRATEGIES.get(mutation_type, "replay_then_page_fallback")
        attempts = []

        async with browser_session(
            self.provider,
            self.db,
            self.lock_manager,
            token,
            target_url=target_url,
            require_sentinel=True,
            close_on_exit=close_on_exit,
        ) as session:
            execution_strategy = strategy
            result = None

            if strategy in {"replay_http", "replay_then_page_fallback"}:
                if replay_callable is None:
                    raise ValueError(f"Mutation {mutation_type} requires replay_callable")
                try:
                    result = await replay_callable(session)
                    append_attempt(attempts, "replay_http", True)
                    execution_strategy = "replay_http"
                except Exception as exc:
                    upstream_status = getattr(exc, "status_code", None)
                    error_code = getattr(exc, "error_code", None)
                    append_attempt(
                        attempts,
                        "replay_http",
                        False,
                        error_code=error_code,
                        upstream_status=upstream_status,
                        message=str(exc),
                    )
                    if strategy == "replay_http" or page_callable is None or not classify_high_risk_failure(exc):
                        raise

            if result is None:
                if page_callable is None:
                    raise ValueError(f"Mutation {mutation_type} requires page_callable for page execution")
                try:
                    session.auth_context = await session.refresh_auth_context(
                        target_url,
                        require_sentinel=True,
                    )
                    result = await page_callable(session)
                    append_attempt(attempts, "page_execute", True)
                    execution_strategy = "page_execute"
                except Exception as exc:
                    append_attempt(
                        attempts,
                        "page_execute",
                        False,
                        error_code=getattr(exc, "code", getattr(exc, "error_code", None)),
                        upstream_status=getattr(exc, "status_code", None),
                        message=str(exc),
                    )
                    raise

            return MutationExecutionResult(
                task_id=result.get("id") if isinstance(result, dict) else task_id,
                raw_result=result,
                strategy=execution_strategy,
                attempts=attempts,
                auth_context=session.auth_context,
                profile_id=session.handle.profile_id,
                window_id=session.handle.window_id,
            )

    @staticmethod
    def ensure_ok_response(response: Dict[str, Any], fallback_message: str) -> Dict[str, Any]:
        """Raise structured errors for page fetch responses."""
        if not response.get("ok"):
            raise extract_upstream_error(response, fallback_message)
        return response

    @staticmethod
    def attempts_to_json(result: MutationExecutionResult) -> str:
        """Serialize mutation attempts for DB storage."""
        return safe_json_dumps([attempt.__dict__ for attempt in result.attempts])
