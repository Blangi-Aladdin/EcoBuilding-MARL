"""Deterministic fixtures and a seeded generator of attendance intervals."""
from dataclasses import dataclass
from random import Random

STEPS = 96


def intervals(*blocks):
    day = [0] * STEPS
    for start, end, people in blocks:
        day[start:end] = [people] * (end-start)
    return day


REFERENCE = intervals((32,48,2),(52,72,2))
DETERMINISTIC = {
    "A": REFERENCE,
    "B1": intervals((32,48,2),(48,52,1),(52,72,2)),
    "B2": intervals((32,72,2)),
    "C": intervals((32,48,2),(52,72,2),(72,80,1)),
    "D": intervals((24,32,1),(32,48,2),(52,64,2)),
    "E": intervals((40,48,1),(48,56,2),(56,64,1)),
    "F": REFERENCE[:48] + [0,1,2,1,0,2,0] + REFERENCE[55:],
}


@dataclass(frozen=True)
class Parameters:
    arrival_steps: tuple = (24, 28, 32, 36, 40)
    departure_steps: tuple = (64, 68, 72, 76, 80, 84)
    lunch_absence_probability: float = 0.65
    weekday_empty_probability: float = 0.15
    weekend_visit_probability: float = 0.35
    weekend_arrival_steps: tuple = (36, 40, 44, 48)
    weekend_departure_steps: tuple = (52, 56, 60, 64)


def generate(seed, *, days=7, start_weekday=0, parameters=Parameters()):
    """Sample person-level attendance blocks, using Monday=0."""
    if type(seed) is not int:
        raise ValueError("An explicit integer seed is required")
    if type(days) is not int or days < 1 or type(start_weekday) is not int or not 0 <= start_weekday < 7:
        raise ValueError("Use a positive day count and a weekday in 0..6")
    p = parameters
    for probability in (p.lunch_absence_probability, p.weekday_empty_probability, p.weekend_visit_probability):
        if not 0 <= probability <= 1:
            raise ValueError("Probabilities must be in 0..1")
    for arrivals, departures in ((p.arrival_steps,p.departure_steps),
                                 (p.weekend_arrival_steps,p.weekend_departure_steps)):
        if (not arrivals or not departures or
            any(type(t) is not int or not 0 <= t <= STEPS for t in (*arrivals,*departures)) or
            max(arrivals) >= min(departures)):
            raise ValueError("Time choices must be ordered integer quarter-hour indices")
    rng = Random(seed)
    profile = []
    for day in range(days):
        weekend = (start_weekday+day)%7 >= 5
        values = [0]*STEPS
        if (weekend and rng.random() < p.weekend_visit_probability or
            not weekend and rng.random() >= p.weekday_empty_probability):
            for _ in range(rng.choice((1,2)) if weekend else 2):
                start = rng.choice(p.weekend_arrival_steps if weekend else p.arrival_steps)
                end = rng.choice(p.weekend_departure_steps if weekend else p.departure_steps)
                lunch = rng.random() < p.lunch_absence_probability
                for slot in range(start,end):
                    if not lunch or not 48 <= slot < 52:
                        values[slot] += 1
        profile.extend(values)
    return profile
