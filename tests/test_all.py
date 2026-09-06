"""
Test runner for all OpenGlassBox Python tests.

This module runs all tests using pytest's discovery mechanism to ensure
comprehensive testing of the entire simulation engine.
"""

import pytest
import sys
import os


def run_all_tests():
    """
    Run all tests using pytest.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Run pytest discovery on the tests directory
    return pytest.main([
        '-v',
        '--tb=short',
        os.path.dirname(os.path.abspath(__file__))
    ])


if __name__ == '__main__':
    # Run all tests when executed directly
    exit_code = run_all_tests()
    sys.exit(exit_code)
