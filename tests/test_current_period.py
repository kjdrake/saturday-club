import datetime
import unittest
from unittest.mock import patch
import server
import test_app

class CurrentPeriodTests(unittest.TestCase):
    def setUp(self):
        self.previous=server._current_period_cache
        server._current_period_cache=None

    def tearDown(self):
        server._current_period_cache=self.previous

    def test_calendar_rollover_and_offseason(self):
        cases=[((2026,8,31),(2026,1)),((2026,9,1),(2026,2)),
               ((2026,11,23),(2026,13)),((2026,11,24),(2026,14)),
               ((2027,1,10),(2026,18)),((2027,3,1),(2027,1))]
        for date,expected in cases:
            with self.subTest(date=date):
                self.assertEqual(server.calendar_period(datetime.date(*date)),dict(zip(('season','week'),expected)))

    def test_feed_and_cache(self):
        with patch.object(server,'fetch_json',return_value={'season':{'year':2028,'type':2},'week':{'number':7}}) as fetch:
            self.assertEqual(server.current_period(),{'season':2028,'week':7})
            self.assertEqual(server.current_period(),{'season':2028,'week':7})
            self.assertEqual(fetch.call_count,1)

    def test_feed_failure_and_invalid_period_use_calendar(self):
        fallback={'season':2026,'week':14}
        for value in [RuntimeError('offline'),{'season':{'year':2026,'type':2},'week':{'number':99}}]:
            server._current_period_cache=None
            with patch.object(server,'calendar_period',return_value=fallback),patch.object(server,'fetch_json',side_effect=value if isinstance(value,Exception) else None,return_value=value):
                self.assertEqual(server.current_period(),fallback)

    def test_preseason_and_postseason(self):
        for kind,week in [(1,1),(3,18)]:
            server._current_period_cache=None
            with patch.object(server,'fetch_json',return_value={'season':{'year':2026,'type':kind}}):
                self.assertEqual(server.current_period(),{'season':2026,'week':week})

class CurrentPeriodRouteTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    call=test_app.AppTests.call

    def test_available_before_sign_in(self):
        with patch.object(server,'current_period',return_value={'season':2026,'week':14}):
            status,result=self.call('current-period')
        self.assertEqual(status,200)
        self.assertEqual(result,{'season':2026,'week':14})
