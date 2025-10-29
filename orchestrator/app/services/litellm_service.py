from uuid import UUID
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
        # Import settings to get configuration
        from ..config import get_settings
        settings = get_settings()

        # Get configuration from settings (which reads from environment)
        self.base_url = settings.litellm_api_base

        # Management API is at root level (without /v1), chat API is at /v1
        # Strip /v1 from base_url for management endpoints (works whether user includes /v1 or not)
        base_url_clean = self.base_url.rstrip('/')
        if base_url_clean.endswith('/v1'):
            self.management_base_url = base_url_clean[:-3]  # Remove /v1
        else:
            self.management_base_url = base_url_clean

        self.master_key = settings.litellm_master_key
        self.default_models = settings.litellm_default_models.split(",") if settings.litellm_default_models else []
        self.team_id = settings.litellm_team_id
        self.email_domain = settings.litellm_email_domain
        self.initial_budget = settings.litellm_initial_budget

        # Only set headers if we have a master key
        self.headers = {
            "Authorization": f"Bearer {self.master_key}",
            "Content-Type": "application/json"
        } if self.master_key else {}

    async def create_user_key(self, user_id: UUID, username: str, models: List[str] = None) -> Dict[str, Any]:
        """
        Create a virtual API key for a user in LiteLLM.

        Args:
            user_id: Internal user ID
            username: Username for identification
            models: List of allowed models (default: inherit from team, allowing all team models)

        Returns:
            Dictionary containing the API key and user details
        """
        # For internal team users, don't restrict models - let team configuration handle it
        # This allows access to all internal team models
        # If you want to restrict specific users, pass a models list explicitly

        # Generate unique user ID for LiteLLM
        litellm_user_id = f"user_{user_id}_{username}"

        async with aiohttp.ClientSession() as session:
            try:
                # Create user in LiteLLM
                user_data = {
                    "user_id": litellm_user_id,
                    "user_email": f"{username}@{self.email_domain}",
                    "user_role": "internal_user",
                    "max_parallel_requests": 10,
                    "metadata": {
                        "tesslate_user_id": str(user_id),
                        "username": username,
                        "created_at": datetime.utcnow().isoformat()
                    }
                }

                async with session.post(
                    f"{self.management_base_url}/user/new",
                    headers=self.headers,
                    json=user_data
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()

                        # If user already exists, that's OK - we'll just create a key for them
                        if "already exists" in error_text.lower():
                            logger.info(f"LiteLLM user {litellm_user_id} already exists, creating key...")
                        else:
                            logger.error(f"Failed to create LiteLLM user: {error_text}")
                            raise Exception(f"Failed to create LiteLLM user: {error_text}")
                    else:
                        user_response = await resp.json()
                        logger.info(f"Created LiteLLM user {litellm_user_id}")

                # Generate API key for the user
                # Use timestamp to ensure unique alias (in case of re-creation)
                timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
                key_data = {
                    "user_id": litellm_user_id,
                    "key_alias": f"{username}_key_{timestamp}",
                    "team_id": self.team_id,  # Access group from configuration
                    "max_budget": self.initial_budget,  # Initial budget from configuration
                    "duration": "365d",  # Key valid for 1 year
                    "metadata": {
                        "tesslate_user_id": str(user_id),
                        "username": username
                    }
                }

                # Only add models restriction if explicitly provided
                # For internal team users, omit this to inherit all team models
                if models is not None:
                    key_data["models"] = models

                async with session.post(
                    f"{self.management_base_url}/key/generate",
                    headers=self.headers,
                    json=key_data
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to generate API key: {error_text}")
                        raise Exception(f"Failed to generate API key: {error_text}")

                    key_response = await resp.json()

                # Add user to the configured team as a member
                try:
                    member_data = {
                        "team_id": self.team_id,
                        "member": {
                            "user_id": litellm_user_id,
                            "role": "user"
                        }
                    }

                    async with session.post(
                        f"{self.management_base_url}/team/member_add",
                        headers=self.headers,
                        json=member_data
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"Added {litellm_user_id} to team {self.team_id}")
                        else:
                            error_text = await resp.text()
                            logger.warning(f"Could not add user to team {self.team_id}: {error_text}")
                            # Don't fail - the team_id in the key might be enough

                except Exception as e:
                    logger.warning(f"Error adding user to team: {e}")
                    # Don't fail the whole key creation

                return {
                    "api_key": key_response.get("key"),
                    "litellm_user_id": litellm_user_id,
                    "models": models if models is not None else "inherited_from_team",
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
                    f"{self.management_base_url}/key/update",
                    headers=self.headers,
                    json=update_data
                ) as resp:
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error updating user models: {e}")
                return False

    async def update_user_team(self, api_key: str, team_id: str, models: List[str] = None) -> bool:
        """
        Update the team/access group for a user's key.

        Args:
            api_key: User's LiteLLM API key
            team_id: Team/access group ID (e.g., "internal")
            models: Optional list of models to set simultaneously

        Returns:
            True if successful, False otherwise
        """
        async with aiohttp.ClientSession() as session:
            try:
                update_data = {
                    "key": api_key,
                    "team_id": team_id
                }

                if models:
                    update_data["models"] = models

                async with session.post(
                    f"{self.management_base_url}/key/update",
                    headers=self.headers,
                    json=update_data
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to update user team: {error_text}")
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error updating user team: {e}")
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
                    f"{self.management_base_url}/key/update",
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
                    f"{self.management_base_url}/spend/key",
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
                    f"{self.management_base_url}/spend/users",
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
                    f"{self.management_base_url}/global/spend",
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
                    f"{self.management_base_url}/key/update",
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
                    f"{self.management_base_url}/key/delete",
                    headers=self.headers,
                    json=delete_data
                ) as resp:
                    return resp.status == 200

            except Exception as e:
                logger.error(f"Error revoking user key: {e}")
                return False

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """
        Get list of available models from LiteLLM.

        Returns:
            List of model objects with id, object, created, owned_by
        """
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.management_base_url}/models",
                    headers=self.headers
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Failed to get models: {error_text}")
                        return []

                    data = await resp.json()
                    return data.get('data', [])

            except Exception as e:
                logger.error(f"Error getting available models: {e}")
                return []


# Singleton instance
litellm_service = LiteLLMService()