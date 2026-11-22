"""Australia: AER plan details -> deals with time-of-use rules, filtered to the postcode."""

from datetime import datetime

from energy_pilot.au_plans import for_postcode, parse, slug
from energy_pilot.tariffs import sched_price

TOU = {"planId": "X1@VEC", "displayName": "Home TOU", "brandName": "AGL", "electricityContract": {
    "tariffPeriod": [{"startDate": "01-01", "endDate": "12-31", "rateBlockUType": "timeOfUseRates", "dailySupplyCharge": "1.00",
                      "timeOfUseRates": [
                          {"rates": [{"unitPrice": "0.30"}], "timeOfUse": [{"days": ["MON", "TUE", "WED", "THU", "FRI"], "startTime": "15:00", "endTime": "21:00"}]},
                          {"rates": [{"unitPrice": "0.10"}], "timeOfUse": [{"days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"], "startTime": "00:00", "endTime": "23:59"}]}]}],
    "solarFeedInTariff": [{"tariffUType": "singleTariff", "singleTariff": {"rates": [{"unitPrice": "0.05"}]}}]}}


def test_time_of_use_plan_with_gst_and_feed_in():
    d = parse(TOU)
    assert d["id"] == "au:X1@VEC" and d["supplier"] == "AGL" and d["fit"] == 0.05  # no GST on feed-in
    assert round(sched_price(d, datetime(2026, 11, 25, 18)), 3) == 0.33  # Wednesday peak, +10 % GST
    assert round(sched_price(d, datetime(2026, 11, 29, 18)), 3) == 0.11  # Sunday: off-peak all day
    assert round(d["monthly"], 2) == round(1.10 * 30.4, 2)


def test_only_residential_electricity_at_the_postcode():
    plans = [{"planId": "a", "fuelType": "ELECTRICITY", "customerType": "RESIDENTIAL", "geography": {"includedPostcodes": ["3000"]}},
             {"planId": "b", "fuelType": "ELECTRICITY", "customerType": "BUSINESS", "geography": {"includedPostcodes": ["3000"]}},
             {"planId": "c", "fuelType": "GAS", "customerType": "RESIDENTIAL", "geography": {"includedPostcodes": ["3000"]}},
             {"planId": "d", "fuelType": "ELECTRICITY", "customerType": "RESIDENTIAL", "geography": {"includedPostcodes": ["2000"]}}]
    assert [p["planId"] for p in for_postcode(plans, "3000")] == ["a"]
    assert slug("Red Energy") == "red-energy" and slug("1st Energy") == "1st-energy"
