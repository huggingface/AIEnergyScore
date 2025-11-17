#!/usr/bin/env python3
"""
Test to verify token parameter parity between batch and non-batch modes.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from reasoning_helpers import is_reasoning_enabled, get_token_parameters


def test_reasoning_detection():
    """Test reasoning detection logic."""
    print("Testing reasoning detection...")

    # Test cases: (reasoning_params, expected_result, description)
    test_cases = [
        (None, False, "None params"),
        ({}, False, "Empty dict"),
        ({"enable_thinking": False}, False, "Thinking disabled"),
        ({"reasoning": False}, False, "Reasoning disabled"),
        ({"reasoning_effort": "off"}, False, "Reasoning effort off"),
        ({"reasoning_effort": "low"}, True, "Reasoning effort low"),
        ({"reasoning_effort": "medium"}, True, "Reasoning effort medium"),
        ({"reasoning_effort": "high"}, True, "Reasoning effort high"),
        ({"enable_thinking": True}, True, "Thinking enabled"),
        ({"some_param": "value"}, True, "Other params present"),
    ]

    passed = 0
    failed = 0

    for params, expected, description in test_cases:
        result = is_reasoning_enabled(params)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {description}: {params} -> {result} (expected {expected})")
        # Use assert for pytest compatibility
        assert (
            result == expected
        ), f"{description} failed: {params} -> {result} (expected {expected})"
        passed += 1

    print(f"\nReasoning detection: {passed} passed, {failed} failed")


def test_token_parameters():
    """Test token parameter generation."""
    print("\nTesting token parameters...")

    # Test cases: (reasoning_params, expected_max, expected_min, description)
    test_cases = [
        (None, 10, 10, "None params (non-reasoning)"),
        ({}, 10, 10, "Empty dict (non-reasoning)"),
        ({"enable_thinking": False}, 10, 10, "Thinking disabled (non-reasoning)"),
        ({"reasoning": False}, 10, 10, "Reasoning disabled (non-reasoning)"),
        ({"reasoning_effort": "off"}, 10, 10, "Reasoning effort off (non-reasoning)"),
        ({"reasoning_effort": "low"}, 8192, 1, "Reasoning effort low (reasoning)"),
        (
            {"reasoning_effort": "medium"},
            8192,
            1,
            "Reasoning effort medium (reasoning)",
        ),
        ({"reasoning_effort": "high"}, 8192, 1, "Reasoning effort high (reasoning)"),
        ({"enable_thinking": True}, 8192, 1, "Thinking enabled (reasoning)"),
    ]

    passed = 0

    for params, expected_max, expected_min, description in test_cases:
        result = get_token_parameters(params)
        expected = {"max_new_tokens": expected_max, "min_new_tokens": expected_min}
        status = "✓" if result == expected else "✗"
        print(f"  {status} {description}:")
        print(f"      Expected: max={expected_max}, min={expected_min}")
        print(
            f"      Got:      max={result['max_new_tokens']}, min={result['min_new_tokens']}"
        )
        # Use assert for pytest compatibility
        assert result == expected, (
            f"{description} failed: expected max={expected_max}, min={expected_min}, "
            f"got max={result['max_new_tokens']}, min={result['min_new_tokens']}"
        )
        passed += 1

    print(f"\nToken parameters: {passed} passed, 0 failed")


def main():
    """Run all tests."""
    print("=" * 70)
    print("Testing Reasoning Parameter Parity")
    print("=" * 70)

    try:
        # Test reasoning detection
        test_reasoning_detection()

        # Test token parameters
        test_token_parameters()

        print("\n" + "=" * 70)
        print("✓ All tests passed!")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print("\n" + "=" * 70)
        print(f"✗ Test failed: {e}")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
