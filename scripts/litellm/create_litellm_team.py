#!/usr/bin/env python3
"""
Create the "internal" team in LiteLLM for access control.

This team is required for users to access cerebras/qwen-3-coder-480b models.

Usage:
    python create_litellm_team.py
"""

import asyncio
import aiohttp
import os
import sys
import logging

# Add the orchestrator app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'orchestrator', 'app'))

from app.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_internal_team():
    """Create the 'internal' team in LiteLLM."""

    settings = get_settings()

    base_url = settings.litellm_api_base.replace('/v1', '')  # Remove /v1 suffix
    master_key = settings.litellm_master_key

    headers = {
        "Authorization": f"Bearer {master_key}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        try:
            # Create the "internal" team
            team_data = {
                "team_alias": "internal",
                "team_id": "internal",
                "models": ["cerebras/qwen-3-coder-480b"],
                "max_budget": 1000.0,  # $1000 budget for the team
                "max_parallel_requests": 100,
                "metadata": {
                    "description": "Internal team for Tesslate Studio users",
                    "created_by": "admin"
                }
            }

            logger.info(f"Creating 'internal' team in LiteLLM at {base_url}/team/new")

            async with session.post(
                f"{base_url}/team/new",
                headers=headers,
                json=team_data
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    logger.info(f"✅ Successfully created 'internal' team")
                    logger.info(f"Response: {result}")
                    return True
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ Failed to create team: {error_text}")
                    return False

        except Exception as e:
            logger.error(f"❌ Error creating team: {e}")
            return False


if __name__ == "__main__":
    result = asyncio.run(create_internal_team())
    sys.exit(0 if result else 1)
