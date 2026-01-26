"""
Theme JSON Validation Schemas

Pydantic models for validating theme JSON structure before storage
and on API responses. Prevents malformed themes from reaching the frontend.

Keep in sync with: app/src/types/theme.ts
"""

import logging
import re
from typing import Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# =============================================================================
# Validation Patterns
# =============================================================================

# Matches hex colors, rgb(), rgba(), hsl(), hsla(), and 'transparent'
CSS_COLOR_PATTERN = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|"  # Hex colors
    r"rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)|"  # rgb()
    r"rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)|"  # rgba()
    r"hsl\(\s*\d{1,3}\s*,\s*\d{1,3}%\s*,\s*\d{1,3}%\s*\)|"  # hsl()
    r"hsla\(\s*\d{1,3}\s*,\s*\d{1,3}%\s*,\s*\d{1,3}%\s*,\s*[\d.]+\s*\)|"  # hsla()
    r"transparent)$",
    re.IGNORECASE,
)

# Matches RGB string like "248, 149, 33"
RGB_STRING_PATTERN = re.compile(r"^\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}$")

# Matches CSS size values like "8px", "1rem", "50%"
CSS_SIZE_PATTERN = re.compile(r"^-?\d+(\.\d+)?(px|em|rem|%|vh|vw)?$")

# Matches CSS duration values like "150ms", "0.3s"
CSS_DURATION_PATTERN = re.compile(r"^\d+(\.\d+)?(ms|s)$")


# =============================================================================
# Validation Helpers
# =============================================================================


def validate_color(value: str, field_name: str = "color") -> str:
    """Validate a CSS color value."""
    if not CSS_COLOR_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be a valid CSS color "
            "(hex, rgb, rgba, hsl, hsla, or transparent)"
        )
    return value


def validate_rgb_string(value: str, field_name: str = "rgb") -> str:
    """Validate an RGB string like '248, 149, 33'."""
    if not RGB_STRING_PATTERN.match(value.strip()):
        raise ValueError(f"{field_name} must be an RGB string like '255, 255, 255'")
    return value


def validate_css_size(value: str, field_name: str = "size") -> str:
    """Validate a CSS size value."""
    if not CSS_SIZE_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be a valid CSS size (e.g., '8px', '1rem', '50%')"
        )
    return value


def validate_css_duration(value: str, field_name: str = "duration") -> str:
    """Validate a CSS duration value."""
    if not CSS_DURATION_PATTERN.match(value):
        raise ValueError(
            f"{field_name} must be a valid CSS duration (e.g., '150ms', '0.3s')"
        )
    return value


# =============================================================================
# Nested Color Schemas
# =============================================================================


class SidebarColors(BaseModel):
    """Sidebar-specific colors."""

    background: str
    text: str
    border: str
    hover: str
    active: str


class InputColors(BaseModel):
    """Input field colors."""

    background: str
    border: str
    borderFocus: str
    text: str
    placeholder: str


class ScrollbarColors(BaseModel):
    """Scrollbar colors."""

    thumb: str
    thumbHover: str
    track: str


class CodeColors(BaseModel):
    """Code block/inline colors."""

    inlineBackground: str
    inlineText: str
    blockBackground: str
    blockBorder: str
    blockText: str


class StatusColors(BaseModel):
    """Status indicator colors."""

    error: str
    errorRgb: str
    success: str
    successRgb: str
    warning: str
    warningRgb: str
    info: str
    infoRgb: str


class ShadowValues(BaseModel):
    """Shadow definitions (CSS box-shadow values)."""

    small: str
    medium: str
    large: str


# =============================================================================
# Main Theme Section Schemas
# =============================================================================


class ThemeColors(BaseModel):
    """Complete theme color palette."""

    primary: str
    primaryHover: str
    primaryRgb: str
    accent: str
    background: str
    surface: str
    surfaceHover: str
    text: str
    textMuted: str
    textSubtle: str
    border: str
    borderHover: str
    sidebar: SidebarColors
    input: InputColors
    scrollbar: ScrollbarColors
    code: CodeColors
    status: StatusColors
    shadow: ShadowValues


class ThemeTypography(BaseModel):
    """Typography settings."""

    fontFamily: str = Field(..., min_length=1)
    fontFamilyMono: str = Field(..., min_length=1)
    fontSizeBase: str
    lineHeight: str


class ThemeSpacing(BaseModel):
    """Spacing and border radius settings."""

    radiusSmall: str
    radiusMedium: str
    radiusLarge: str
    radiusXl: str


class ThemeAnimation(BaseModel):
    """Animation timing settings."""

    durationFast: str
    durationNormal: str
    durationSlow: str
    easing: str


# =============================================================================
# Complete Theme Schema
# =============================================================================


class ThemeJsonSchema(BaseModel):
    """
    Complete theme JSON schema for validation.
    This validates the theme_json column content in the themes table.
    """

    colors: ThemeColors
    typography: ThemeTypography
    spacing: ThemeSpacing
    animation: ThemeAnimation

    model_config = {"extra": "forbid"}  # Reject unknown fields


class ThemeCreateRequest(BaseModel):
    """Request schema for creating a new theme (admin only)."""

    id: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=100)
    mode: Literal["dark", "light"]
    author: Optional[str] = Field(default="Tesslate", max_length=100)
    version: Optional[str] = Field(default="1.0.0", max_length=20)
    description: Optional[str] = Field(default=None, max_length=500)
    theme_json: ThemeJsonSchema
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 99


class ThemeUpdateRequest(BaseModel):
    """Request schema for updating a theme (admin only)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    mode: Optional[Literal["dark", "light"]] = None
    author: Optional[str] = Field(default=None, max_length=100)
    version: Optional[str] = Field(default=None, max_length=20)
    description: Optional[str] = Field(default=None, max_length=500)
    theme_json: Optional[ThemeJsonSchema] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# =============================================================================
# Validation Utility Functions
# =============================================================================


def validate_theme_json(theme_json: dict) -> Tuple[bool, Optional[str], Optional[ThemeJsonSchema]]:
    """
    Validate theme JSON data and return validation result.

    Args:
        theme_json: The theme JSON dict to validate

    Returns:
        Tuple of (is_valid, error_message, validated_schema)

    Example:
        is_valid, error, schema = validate_theme_json(theme.theme_json)
        if not is_valid:
            logger.warning(f"Theme validation failed: {error}")
    """
    try:
        validated = ThemeJsonSchema.model_validate(theme_json)
        return True, None, validated
    except Exception as e:
        error_msg = str(e)
        logger.warning(f"Theme JSON validation failed: {error_msg}")
        return False, error_msg, None


def validate_theme_json_safe(theme_json: dict) -> bool:
    """
    Validate theme JSON and return simple boolean.
    Logs warnings on failure.

    Args:
        theme_json: The theme JSON dict to validate

    Returns:
        True if valid, False otherwise
    """
    is_valid, _, _ = validate_theme_json(theme_json)
    return is_valid


def get_theme_validation_errors(theme_json: dict) -> list[str]:
    """
    Get detailed validation errors for a theme JSON.

    Args:
        theme_json: The theme JSON dict to validate

    Returns:
        List of error messages (empty if valid)
    """
    try:
        ThemeJsonSchema.model_validate(theme_json)
        return []
    except Exception as e:
        # Pydantic v2 provides detailed errors
        if hasattr(e, "errors"):
            return [
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ]
        return [str(e)]
