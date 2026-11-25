from datetime import datetime
import unittest

from ecobuilding.observations import ObservationManager, VARIABLES, joules_to_kwh, m3_s_to_m3_h, zone_interval


class Exchange:
    def __init__(self):
        self.keys = list(VARIABLES)
        self.missing = set()
        self.values = dict.fromkeys(self.keys,0.0)
        self.values.update(people=2,indoor_c=20,indoor_rh_pct=50,co2_ppm=1000)
        self.calls = []
        self.duration, self.end = 900,900
        self.env = 1
        self.warmup = False

    def api_data_fully_ready(self,s): return True
    def api_error_flag(self,s): return False
    def warmup_flag(self,s): return self.warmup
    def current_environment_num(self,s): return self.env
    def year(self,s): return 2024
    def calendar_year(self,s): return 2024
    def month(self,s): return 2
    def day_of_month(self,s): return 29
    def day_of_week(self,s): return 5
    def day_of_year(self,s): return 60
    def hour(self,s): return 0
    def minutes(self,s): return int(self.end/60)
    def zone_time_step_number(self,s): return round(self.end/900)
    def num_time_steps_in_hour(self,s): return 4
    def daylight_savings_time_indicator(self,s): return 0
    def zone_time_step(self,s): return .25
    def system_time_step(self,s): return self.duration/3600
    def current_time(self,s): return self.end/3600

    def get_variable_handle(self,s,name,key):
        logical = next(k for k,v in VARIABLES.items() if (v.name,v.key)==(name,key))
        return -1 if logical in self.missing else self.keys.index(logical)+100*s

    def get_variable_value(self,s,handle):
        assert handle//100 == s
        name = self.keys[handle%100]
        self.calls.append(name)
        return self.values[name]


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.api=Exchange()
        self.manager=ObservationManager(self.api)
        self.manager.initialize(1)

    def sample(self,duration,end,power):
        self.api.duration,self.api.end=duration,end
        self.api.values.update(heat_electric_w=power,heat_convective_w=power)
        return self.manager.collect_system_step()

    def finish(self, joules, **metadata):
        self.api.values["heat_j"]=joules
        return self.manager.finalize_zone_step(**metadata)

    def test_conversions(self):
        self.assertAlmostEqual(joules_to_kwh(1_500_000),.4166666666666667)
        self.assertAlmostEqual(m3_s_to_m3_h(40/3600),40)

    def test_constant_power(self):
        self.sample(900,900,1000)
        observation=self.finish(900000)
        self.assertEqual(observation["energy"]["heating_kwh"],.25)
        self.assertEqual(observation["energy"]["total_mean_w"],1000)

    def test_variable_power_and_durations(self):
        self.sample(300,300,1000)
        self.sample(600,900,2000)
        obs=self.finish(1500000)
        self.assertEqual(obs["energy"]["heating_j"],1500000)
        self.assertAlmostEqual(obs["energy"]["total_mean_w"],1666.6666666666667)
        self.assertEqual(obs["time"]["hvac_seconds"],[300,600])

    def test_heating_energy_is_read_once(self):
        self.sample(300,300,1000)
        self.sample(600,900,2000)
        self.assertNotIn("heat_j",self.api.calls)
        self.finish(1500000)
        self.manager.get_observation()
        self.manager.get_observation()
        self.assertEqual(self.api.calls.count("heat_j"),1)

    def test_repeated_hvac_callback_is_rejected(self):
        self.sample(450,450,0)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            self.sample(450,450,0)

    def test_incomplete_zone_duration_fails(self):
        self.sample(450,900,0)
        with self.assertRaisesRegex(ValueError,"durations"):
            self.finish(0)

    def test_next_zone_has_fresh_accumulators(self):
        self.sample(900,900,1000)
        self.finish(900000)
        self.sample(900,1800,0)
        self.assertEqual(self.finish(0)["energy"]["total_j"],0)

    def test_nan_and_infinity_rejected(self):
        for invalid in (float("nan"),float("inf"),-float("inf")):
            self.api.values["indoor_c"]=invalid
            with self.assertRaises(ValueError):
                self.sample(900,900,0)

    def test_missing_mandatory_handle(self):
        self.manager.detach()
        self.api.missing.add("co2_ppm")
        with self.assertRaisesRegex(RuntimeError,"co2_ppm"):
            self.manager.initialize(1)

    def test_missing_optional_handle_is_explicit(self):
        self.manager.detach()
        self.api.missing.add("dx_coil_j")
        self.manager.initialize(1)
        self.sample(900,900,0)
        diagnostics=self.finish(0)["diagnostics"]
        self.assertIn("dx_coil_j",diagnostics["unavailable"])
        self.assertIsNone(diagnostics["substep_energy_j"]["dx_coil_j"])

    def test_ordinary_timestamps(self):
        for hour in (7,11,17):
            start,end=zone_interval(2024,8,7,hour,4,4)
            self.assertEqual((start.hour,start.minute,end.hour,end.minute),(hour,45,hour+1,0))

    def test_midnight(self):
        start,end=zone_interval(2024,8,7,23,4,4)
        self.assertEqual(start,datetime(2024,8,7,23,45))
        self.assertEqual(end,datetime(2024,8,8))

    def test_leap_month_and_year_rollover(self):
        self.assertEqual(zone_interval(2024,2,29,23,4,4)[1],datetime(2024,3,1))
        self.assertEqual(zone_interval(2023,2,28,23,4,4)[1],datetime(2023,3,1))
        self.assertEqual(zone_interval(2024,12,31,23,4,4)[1],datetime(2025,1,1))

    def test_presence_and_historical_action(self):
        for index,people in enumerate((0,1,2),1):
            self.api.values["people"]=people
            self.sample(900,900*index,0)
            action=(1,2,0)
            obs=self.finish(0,last_applied=action,hvac_overrides_active=index<3)
            self.assertEqual(obs["occupancy"],{"people":people,"presence":int(people>0)})
            self.assertEqual(obs["actions"]["last_applied"],action)
            self.assertEqual(obs["actions"]["active_action"],action if index<3 else None)

    def test_getting_observation_cannot_mutate_snapshot(self):
        self.sample(900,900,0)
        obs=self.finish(0)
        obs["energy"]["total_j"]=999
        self.assertEqual(self.manager.get_observation()["energy"]["total_j"],0)

    def test_warmup_and_environment_guard(self):
        self.api.warmup=True
        with self.assertRaisesRegex(RuntimeError,"Warmup"):
            self.sample(900,900,0)
        self.api.warmup=False
        self.sample(900,900,0)
        self.finish(0)
        self.api.env=2
        with self.assertRaisesRegex(RuntimeError,"different environment"):
            self.sample(900,1800,0)

    def test_detach_discards_data_and_rebinds(self):
        self.sample(900,900,0)
        self.finish(0)
        self.sample(300,1200,2000)
        self.manager.detach()
        self.assertIsNone(self.manager.get_observation())
        self.manager.initialize(2)
        self.sample(900,900,0)
        self.assertEqual(self.finish(0)["energy"]["total_j"],0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
