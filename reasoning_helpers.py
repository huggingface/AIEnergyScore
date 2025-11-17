#!/usr/bin/env python3
"""
Shared utilities for reasoning parameter detection and token configuration.

This module provides common functionality for both batch and non-batch execution modes
to ensure consistent handling of reasoning-aware token parameters.
"""

from typing import Dict, Optional


def is_reasoning_enabled(reasoning_params: Optional[Dict]) -> bool:
    """Check if reasoning is actually enabled based on parameter values.

    Args:
        reasoning_params: Dictionary of reasoning parameters

    Returns:
        True if reasoning is enabled, False otherwise

    Examples:
        >>> is_reasoning_enabled(None)
        False
        >>> is_reasoning_enabled({'enable_thinking': False})
        False
        >>> is_reasoning_enabled({'reasoning_effort': 'off'})
        False
        >>> is_reasoning_enabled({'reasoning_effort': 'high'})
        True
    """
    if not reasoning_params:
        return False

    # Check common reasoning disable patterns
    if reasoning_params.get("enable_thinking") is False:
        return False
    if reasoning_params.get("reasoning") is False:
        return False
    if reasoning_params.get("reasoning_effort") == "off":
        return False

    # Any other parameters present = reasoning enabled
    return True


def get_token_parameters(reasoning_params: Optional[Dict]) -> Dict[str, int]:
    """Get appropriate token parameters based on reasoning mode.

    Args:
        reasoning_params: Dictionary of reasoning parameters

    Returns:
        Dictionary with 'max_new_tokens' and 'min_new_tokens' keys

    Examples:
        >>> get_token_parameters(None)
        {'max_new_tokens': 10, 'min_new_tokens': 10}
        >>> get_token_parameters({'reasoning_effort': 'high'})
        {'max_new_tokens': 8192, 'min_new_tokens': 1}
        >>> get_token_parameters({'enable_thinking': False})
        {'max_new_tokens': 10, 'min_new_tokens': 10}
    """
    if is_reasoning_enabled(reasoning_params):
        # For reasoning modes: Allow model to generate as needed
        return {"max_new_tokens": 8192, "min_new_tokens": 1}
    else:
        # For non-reasoning modes: Fixed short response (10 tokens)
        return {"max_new_tokens": 10, "min_new_tokens": 10}
