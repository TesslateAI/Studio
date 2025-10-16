"""
LiteLLM Service for managing user virtual keys and tracking usage.
"""

import aiohttp
import uuid
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)


class LiteLLMService:
    """Service for interacting with LiteLLM proxy for user management and usage tracking."""

    def __init__(self):
        # Get configuration from environment variables
        self.base_url = os.getenv("LITELLM_API_BASE", "https://apin.tesslate.com")
        self.master_key = os.getenv("LITELLM_MASTER_KEY", "REDACTED_LITELLM_MASTER_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.master_key}",
            "Content-Type": "application/json"
        }

    async def create_user_key(self, user_id: int, username: str, models: List[str] = None) -> Dict[str, Any]:
        """
        Create a virtual API key for a user in LiteLLM.

        Args:
            user_id: Internal user ID
            username: Username for identification
            models: List of allowed models (default: all available models)

        Returns:
            Dictionary containing the API key and user details
        """
        if models is None:
            # Default models available to new users
            models = ["UIGEN-FX-SMALL", "WEBGEN-SMALL"]

        # Generate unique user ID for LiteLLM
        litellm_user_id = f"user_{user_id}_{username}"

        async with aiohttp.ClientSession() as session:
            try:
                # Create user in LiteLLM
                user_data = {
                    "user_id": litellm_user_id,
                    "user_email": f"{username}@tesslate.internal",
                    "user_role": "internal_user",
                    "max_parallel_requests": 10,
                    "metadata": {
                        "tesslate_user_id": user_id,
                        "username": username,
                        "created_at": datetime.utcnow().isoformat()
                    }
                }

                async with session.post(
                    f"{self.base_url}/user/new",
                    headers=self.headers,
                    json=user_data
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to create LiteLLM user: {error_text}")
                        raise Exception(f"Failed to create LiteLLM user: {error_text}")

                    user_response = await resp.json()

                # Generate API key for the user
                key_data = {
                    "user_id": litellm_user_id,
                    "key_alias": f"{username}_key",
                    "models": models,
                    "max_budget": 10.0,  # Initial budget in USD
                    "duration": "365d",  # Key valid for 1 year
                    "metadata": {
                        "tesslate_user_id": user_id,
                        "username": username
                    }
                }

                async with session.post(
                    f"{self.base_url}/key/generate",
                    headers=self.headers,
                    json=key_data
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to generate API key: {error_text}")
                        raise Exception(f"Failed to generate API key: {error_text}")

                    key_response = await resp.json()

                return {
                    "api_key": key_response.get("key"),
                    "litellm_user_id": litellm_user_id,
                    "models": models,
                    "budget": key_data["max_budget"]
                }

            except Exception as e:
                logger.error(f"Error creating LiteLLM user key: {e}")
                raise

    async def update_user_models(self, api_key: str, models: List[str]) -> bool:
        """
        Update the models available to a user.

        Args:
            api_key: User's LiteLLM API key
            models: New list of allowed models

        Returns:
            True if successful, False otherwise
        """
        async with aiohttp.ClientSession() as session:
            try:
                update_data = {
                    "key": api_key,
                    "models": models
                }

                async with session.post(
                    f"{self.base_url}/key/update",
                    headers=self.headers,
                    json=update_data
                ) as resp:
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error updating user models: {e}")
                return False

    async def add_user_budget(self, api_key: str, amount: float) -> bool:
        """
        Add budget to a user's account.

        Args:
            api_key: User's LiteLLM API key
            amount: Amount to add in USD

        Returns:
            True if successful, False otherwise
        """
        async with aiohttp.ClientSession() as session:
            try:
                update_data = {
                    "key": api_key,
                    "max_budget": amount,
                    "budget_action": "add"  # Add to existing budget
                }

                async with session.post(
                    f"{self.base_url}/key/update",
                    headers=self.headers,
                    json=update_data
                ) as resp:
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error adding user budget: {e}")
                return False

    async def get_user_usage(self, api_key: str, start_date: datetime = None) -> Dict[str, Any]:
        """
        Get usage statistics for a user.

        Args:
            api_key: User's LiteLLM API key
            start_date: Start date for usage (default: last 30 days)

        Returns:
            Dictionary containing usage statistics
        """
        if start_date is None:
            start_date = datetime.utcnow() - timedelta(days=30)

        async with aiohttp.ClientSession() as session:
            try:
                params = {
                    "api_key": api_key,
                    "start_date": start_date.isoformat()
                }

                async with session.get(
                    f"{self.base_url}/spend/key",
                    headers=self.headers,
                    params=params
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to get user usage: {error_text}")
                        return {}

                    return await resp.json()

            except Exception as e:
                logger.error(f"Error getting user usage: {e}")
                return {}

    async def get_all_users_usage(self, start_date: datetime = None) -> List[Dict[str, Any]]:
        """
        Get usage statistics for all users (admin only).

        Args:
            start_date: Start date for usage (default: last 30 days)

        Returns:
            List of user usage statistics
        """
        if start_date is None:
            start_date = datetime.utcnow() - timedelta(days=30)

        async with aiohttp.ClientSession() as session:
            try:
                params = {
                    "start_date": start_date.isoformat()
                }

                async with session.get(
                    f"{self.base_url}/spend/users",
                    headers=self.headers,
                    params=params
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to get all users usage: {error_text}")
                        return []

                    return await resp.json()

            except Exception as e:
                logger.error(f"Error getting all users usage: {e}")
                return []

    async def get_global_stats(self) -> Dict[str, Any]:
        """
        Get global statistics from LiteLLM (admin only).

        Returns:
            Dictionary containing global statistics
        """
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.base_url}/global/spend",
                    headers=self.headers
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to get global stats: {error_text}")
                        return {}

                    return await resp.json()

            except Exception as e:
                logger.error(f"Error getting global stats: {e}")
                return {}

    async def enable_user_passthrough(self, api_key: str, user_api_keys: Dict[str, str]) -> bool:
        """
        Enable passthrough mode for a user with their own API keys.

        Args:
            api_key: User's LiteLLM API key
            user_api_keys: Dictionary of provider -> API key mappings

        Returns:
            True if successful, False otherwise
        """
        async with aiohttp.ClientSession() as session:
            try:
                update_data = {
                    "key": api_key,
                    "metadata": {
                        "passthrough_enabled": True,
                        "user_api_keys": user_api_keys
                    }
                }

                async with session.post(
                    f"{self.base_url}/key/update",
                    headers=self.headers,
                    json=update_data
                ) as resp:
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error enabling passthrough: {e}")
                return False

    async def revoke_user_key(self, api_key: str) -> bool:
        """
        Revoke a user's API key.

        Args:
            api_key: User's LiteLLM API key to revoke

        Returns:
            True if successful, False otherwise
        """
        async with aiohttp.ClientSession() as session:
            try:
                delete_data = {
                    "keys": [api_key]
                }

                async with session.post(
                    f"{self.base_url}/key/delete",
                    headers=self.headers,
                    json=delete_data
                ) as resp:
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error revoking user key: {e}")
                return False


# Singleton instance
litellm_service = LiteLLMService()