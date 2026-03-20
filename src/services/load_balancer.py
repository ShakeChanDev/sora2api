"""Load balancing module"""
import random
import asyncio
from typing import Optional
from collections import defaultdict
from ..core.models import Token
from ..core.config import config
from .token_manager import TokenManager
from .token_lock import TokenLock
from .concurrency_manager import ConcurrencyManager
from ..core.logger import debug_logger

class LoadBalancer:
    """Token load balancer with random selection and round-robin polling"""

    def __init__(self, token_manager: TokenManager, concurrency_manager: Optional[ConcurrencyManager] = None):
        self.token_manager = token_manager
        self.concurrency_manager = concurrency_manager
        # Use image timeout from config as lock timeout
        self.token_lock = TokenLock(lock_timeout=config.image_timeout)
        # Round-robin state: stores last used token_id for each scenario (image/video/default)
        # Resets to None on restart
        self._round_robin_state = {"image": None, "video": None, "default": None}
        self._rr_lock = asyncio.Lock()

    async def _select_round_robin(self, tokens: list[Token], scenario: str) -> Optional[Token]:
        """Select tokens in round-robin order for the given scenario"""
        if not tokens:
            return None
        tokens_sorted = sorted(tokens, key=lambda t: t.id)

        async with self._rr_lock:
            last_id = self._round_robin_state.get(scenario)
            start_idx = 0
            if last_id is not None:
                # Find the position of last used token and move to next
                for idx, token in enumerate(tokens_sorted):
                    if token.id == last_id:
                        start_idx = (idx + 1) % len(tokens_sorted)
                        break
            selected = tokens_sorted[start_idx]
            # Update state for next selection
            self._round_robin_state[scenario] = selected.id

        return selected

    async def select_token(self, for_image_generation: bool = False, for_video_generation: bool = False, require_pro: bool = False) -> Optional[Token]:
        """
        Select a token using random load balancing

        Args:
            for_image_generation: If True, only select tokens that are not locked for image generation and have image_enabled=True
            for_video_generation: If True, filter out tokens with Sora2 quota exhausted (sora2_cooldown_until not expired), tokens that don't support Sora2, and tokens with video_enabled=False
            require_pro: If True, only select tokens with ChatGPT Pro subscription (plan_type="chatgpt_pro")

        Returns:
            Selected token or None if no available tokens
        """
        active_tokens = await self.token_manager.get_active_tokens()

        if not active_tokens:
            return None

        # Filter for Pro tokens if required
        if require_pro:
            pro_tokens = [token for token in active_tokens if token.plan_type == "chatgpt_pro"]
            if not pro_tokens:
                return None
            active_tokens = pro_tokens

        # If for video generation, filter out tokens with Sora2 quota exhausted and tokens without Sora2 support
        if for_video_generation:
            from datetime import datetime
            available_tokens = []
            for token in active_tokens:
                # Skip tokens that don't have video enabled
                if not token.video_enabled:
                    continue

                # Skip tokens that don't support Sora2
                if not token.sora2_supported:
                    continue

                # Check if Sora2 cooldown has expired and refresh if needed
                if token.sora2_cooldown_until and token.sora2_cooldown_until <= datetime.now():
                    await self.token_manager.refresh_sora2_remaining_if_cooldown_expired(token.id)
                    # Reload token data after refresh
                    token = await self.token_manager.db.get_token(token.id)

                # Skip tokens that are in Sora2 cooldown (quota exhausted)
                if token and token.sora2_cooldown_until and token.sora2_cooldown_until > datetime.now():
                    continue

                provider_name = (token.browser_provider if token.browser_provider else config.browser_provider).strip() or "nst"
                if provider_name != "nst":
                    continue
                if not token.browser_profile_id:
                    continue
                if not token.proxy_url:
                    continue

                if token:
                    available_tokens.append(token)

            if not available_tokens:
                return None

            active_tokens = available_tokens

        # If for image generation, filter out locked tokens and tokens without image enabled
        if for_image_generation:
            available_tokens = []
            for token in active_tokens:
                # Skip tokens that don't have image enabled
                if not token.image_enabled:
                    continue

                if not await self.token_lock.is_locked(token.id):
                    # Check concurrency limit if concurrency manager is available
                    if self.concurrency_manager and not await self.concurrency_manager.can_use_image(token.id):
                        continue
                    available_tokens.append(token)

            if not available_tokens:
                return None

            # Check if polling mode is enabled
            if config.call_logic_mode == "polling":
                scenario = "image"
                return await self._select_round_robin(available_tokens, scenario)

            # Random selection from available tokens
            return random.choice(available_tokens)
        else:
            # For video generation, check concurrency limit
            if for_video_generation and self.concurrency_manager:
                available_tokens = []
                for token in active_tokens:
                    if await self.concurrency_manager.can_use_video(token.id):
                        available_tokens.append(token)
                if not available_tokens:
                    return None

                # Check if polling mode is enabled
                if config.call_logic_mode == "polling":
                    scenario = "video"
                    return await self._select_round_robin(available_tokens, scenario)

                return random.choice(available_tokens)
            else:
                # For video generation without concurrency manager, no additional filtering
                # Check if polling mode is enabled
                if config.call_logic_mode == "polling":
                    scenario = "video" if for_video_generation else "default"
                    return await self._select_round_robin(active_tokens, scenario)

                return random.choice(active_tokens)
