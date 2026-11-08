"""Power left when the plan ends is worth what refilling it costs - not the average of an expensive day."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_pilot.engine import Battery, Hour, end_price, plan_battery

T0 = datetime(2026, 11, 8, 16, tzinfo=ZoneInfo("Europe/Copenhagen"))
# tonight cheap (2.5), tomorrow morning 4.4, tomorrow evening 6-7.5
PRICES = [4.7, 4.7, 4.7, 4.6, 3.2, 3.0, 2.7, 2.6, 2.5, 2.5, 2.5, 2.5, 2.6, 2.7, 3.6, 4.3, 4.5, 4.4, 4.1, 4.0,
          4.0, 4.0, 4.3, 5.7, 5.6, 7.5, 6.8, 6.0, 5.2, 3.6, 3.2, 2.9]
HOURS = [Hour(T0 + timedelta(hours=i), p, 0.0, 1.0, 0.0) for i, p in enumerate(PRICES)]
B = Battery(capacity_kwh=13, min_soc=10, efficiency=0.92)


def test_end_value_is_the_refill_price():
    assert end_price(HOURS, B) < 2.8
    assert end_price(HOURS[:5], B) > 4.0  # no night ahead: the median as before


def test_uses_the_morning_and_covers_the_evening_without_buying_late():
    p = plan_battery(HOURS, 76, B, end_value=end_price(HOURS, B))
    by = {s.start.hour: s for s in p.steps[12:]}  # tomorrow
    assert by[7].action == "discharge"
    assert all(by[h].action == "discharge" for h in (17, 18, 19))
    assert by[21].action != "charge_grid"
