"""Test doubles reserved for the 37.2.4 software campaign."""

from threading import Event


class StateManagerDouble:
    def __init__(self, events):
        self.events = events
        self.live = set()
        self.next_state = 0

    def new_state(self):
        self.next_state += 1
        self.live.add(self.next_state)
        self.events.append(("new_state", self.next_state))
        return self.next_state

    def delete_state(self, state):
        self.live.remove(state)
        self.events.append(("delete_state", state))


class ExchangeDouble:
    def __init__(self, events):
        self.events = events
        self.error = False

    def request_variable(self, state, name, key):
        self.events.append(("request_variable", state, name, key))

    def api_error_flag(self, state):
        return self.error


class RuntimeDouble:
    def __init__(self, events, driver):
        self.events = events
        self.driver = driver
        self.callbacks = {}
        self.stop_requested = Event()

    def __getattr__(self, name):
        if not name.startswith("callback_"):
            raise AttributeError(name)

        def register(state, function):
            self.callbacks.setdefault(name, []).append(function)
            self.events.append(("register", state, name))

        return register

    def set_console_output_status(self, state, enabled):
        self.events.append(("console", state, enabled))

    def run_energyplus(self, state, args):
        self.events.append(("run", state, tuple(args)))
        return self.driver(self, state)

    def emit(self, name, state):
        for function in self.callbacks.get(name, ()):
            function(state)

    def stop_simulation(self, state):
        self.events.append(("stop", state))
        self.stop_requested.set()

    def clear_callbacks(self):
        self.callbacks.clear()
        self.events.append(("clear_callbacks",))


class APIDouble:
    """Assign to a single test worker before invoking its inherited start()."""

    def __init__(self, driver):
        self.events = []
        self.state_manager = StateManagerDouble(self.events)
        self.exchange = ExchangeDouble(self.events)
        self.runtime = RuntimeDouble(self.events, driver)


from datetime import datetime, timedelta

from ecobuilding.observations import VARIABLES
from ecobuilding.sinergym_adapter.simulator import EcoBuildingSimulator

WEATHER = "callback_begin_zone_timestep_before_set_current_weather"
HEAT = "callback_begin_zone_timestep_before_init_heat_balance"
PREDICT = "callback_after_predictor_after_hvac_managers"
SYSTEM = "callback_end_system_timestep_after_hvac_reporting"
ZONE = "callback_end_zone_timestep_after_zone_reporting"


class ZoneExchange(ExchangeDouble):
    """Clock, handles and known numeric samples, with zero physical calculations."""

    def __init__(self, events):
        super().__init__(events)
        self.warm = False
        self.ready = True
        self.missing = None
        self.when = datetime(2025, 1, 1)
        self.weekday = 2
        self.duration = self.elapsed = 0
        self.load = -700
        self.actuators = {}
        self.writes = []
        self.handles = {}
        self.read_error = None
        self.fail_write = None
        self.bad_duration = False

    def warmup_flag(self, state): return self.warm
    def kind_of_sim(self, state): return 3
    def api_data_fully_ready(self, state): return self.ready
    def daylight_savings_time_indicator(self, state): return False
    def num_time_steps_in_hour(self, state): return 4
    def calendar_year(self, state): return self.when.year
    def year(self, state): return 2017
    def month(self, state): return self.when.month
    def day_of_month(self, state): return self.when.day
    def hour(self, state): return self.when.hour
    def minutes(self, state): return self.when.minute + 15
    def zone_time_step_number(self, state): return self.when.minute // 15 + 1
    def current_environment_num(self, state): return 1
    def day_of_week(self, state): return self.weekday
    def day_of_year(self, state): return self.when.timetuple().tm_yday
    def zone_time_step(self, state): return 0.25
    def system_time_step(self, state): return self.duration / 3600
    def current_time(self, state):
        return self.when.hour + self.when.minute / 60 + self.elapsed / 3600

    def _handle(self, state, name):
        self.events.append(("resolve", state, name))
        if name == self.missing:
            return -1
        return self.handles.setdefault((state, name), state * 1000 + len(self.handles) + 1)

    def get_actuator_handle(self, state, *key):
        return self._handle(state, key[-1])

    def get_variable_handle(self, state, name, key):
        return self._handle(state, (name, key))

    def set_actuator_value(self, state, handle, value):
        self.writes.append((self.when, handle, value))
        if self.fail_write == len(self.writes):
            self.error = True
        self.actuators[handle] = value

    def reset_actuator(self, state, handle):
        self.set_actuator_value(state, handle, None)

    def get_variable_value(self, state, handle):
        pair = next(key for (owner, key), h in self.handles.items() if owner == state and h == handle)
        if pair == self.read_error:
            self.error = True
        logical = next(k for k, v in VARIABLES.items() if (v.name, v.key) == pair)
        people_handle = self.handles.get((state, "OFFICE OCCUPANCY"))
        people = 2 * self.actuators.get(people_handle, 0.5)
        return {
            "people": people, "indoor_c": 24.0, "indoor_rh_pct": 55.0 if self.elapsed == 900 else 49.0,
            "co2_ppm": 610.0, "predicted_load_w": self.load,
            "heat_electric_w": 80, "heat_j": 72000, "dx_electric_w": 20,
            "vent_j": 3 * self.duration, "dx_speed_level": 1, "dx_total_w": 30,
            "dx_sensible_w": 20, "dx_latent_w": 10,
        }.get(logical, 0.0)


class WorkerFactory:
    """Build the real worker with a fresh, instance-local simulated external API."""

    def __init__(self, driver=None, setup=None, last_code=0):
        self.workers = []
        self.driver = driver
        self.setup = setup
        self.last_code = last_code

    def __call__(self, *args, **kwargs):
        api = APIDouble(lambda runtime, state: self.run(worker, runtime, state))
        api.state_manager.next_state = len(self.workers)
        api.exchange = ZoneExchange(api.events)
        worker = EcoBuildingSimulator(*args, **kwargs, _api=api)
        if self.setup:
            self.setup(worker)
        self.workers.append(worker)
        return worker

    def run(self, worker, runtime, state):
        if self.driver:
            return self.driver(worker, runtime, state)
        return self.drive(worker, runtime, state)

    def drive(self, worker, runtime, state):
        e = worker.exchange
        episode = worker.episode_config
        first = datetime(2025, *episode.first)
        e.warm = True
        self.zone(runtime, state, e)
        e.warm = False
        runtime.emit("callback_after_new_environment_warmup_complete", state)
        for index in range(-2, episode.steps):
            if runtime.stop_requested.is_set():
                return 0
            e.when = first + timedelta(minutes=15 * index)
            e.weekday = (episode.first_weekday + (e.when.date() - first.date()).days + 1) % 7 + 1
            self.zone(runtime, state, e)
        return self.last_code

    @staticmethod
    def zone(runtime, state, exchange):
        exchange.elapsed = 0
        for name in (WEATHER, HEAT):
            runtime.emit(name, state)
        for duration, load in ((300, -700), (600, 80)):
            exchange.load = load
            runtime.emit(PREDICT, state)
            exchange.duration = duration - (1 if exchange.bad_duration else 0)
            exchange.elapsed += duration
            runtime.emit(SYSTEM, state)
        runtime.emit(ZONE, state)
