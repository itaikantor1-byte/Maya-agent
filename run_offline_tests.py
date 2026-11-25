"""Run regression suite with all outbound HTTP disabled."""
import unittest
from unittest.mock import patch

with patch('requests.sessions.Session.request', side_effect=AssertionError('Outbound network forbidden in tests')):
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_main', 'test_policy_efficiency', 'test_queue'])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
