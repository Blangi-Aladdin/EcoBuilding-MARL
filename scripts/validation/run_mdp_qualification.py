"""Run only the four requested train weeks and an identical winter replay."""
import argparse
from datetime import date
from hashlib import file_digest
from itertools import product
import json
from pathlib import Path
from random import Random
from unittest.mock import patch

from ecobuilding.episodes import DEFAULT_CONFIG, EpisodePlan, EpisodeScenario
from ecobuilding.observations import VARIABLES
from ecobuilding.sinergym_adapter import EcoBuildingEnv, STATE_NAMES
from ecobuilding.sinergym_adapter.model import prepare_episode_inputs
from ecobuilding.sinergym_adapter.simulator import EcoBuildingSimulator
from sinergym.simulators.eplus import EnergyPlus

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT/'models/office_1zone.epJSON'
EPW = ROOT/'models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw'


def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def log(stream, row):
    stream.write(json.dumps(row, allow_nan=False)+'\n')


def reported_inputs(*args, **kwargs):
    model, epw, output = prepare_episode_inputs(*args, **kwargs)
    copy = json.loads(model.read_bytes())
    variables = copy['Output:Variable']
    original = set((v['key_value'].upper(), v['variable_name'].upper(), v['reporting_frequency'].lower())
                   for v in variables.values())
    for key, spec in VARIABLES.items():
        if (spec.key, spec.name.upper(), 'timestep') not in original:
            variables['MDP qualification '+key] = {
                'key_value': spec.key, 'variable_name': spec.name, 'reporting_frequency': 'Timestep'}
    model.write_text(json.dumps(copy, indent=2)+'\n')
    return model, epw, output


def execute(out, name, spec, actions):
    target=out/name
    target.mkdir()
    write(target/'manifest.json', spec)
    write(target/'actions.json',actions)
    scenario=EpisodeScenario.from_record(spec['scenario'], spec['reference_year'])
    worker=None
    env=EcoBuildingEnv(MODEL,EPW,target/'engine',scenario.episode)
    with (target/'substeps.jsonl').open('w') as samples, (target/'control.jsonl').open('w') as control, (
            target/'observations.jsonl').open('w') as observations:
        def factory(*args, **kwargs):
            nonlocal worker
            worker=EcoBuildingSimulator(*args, **kwargs)
            assert type(worker).start is EnergyPlus.start
            observe=worker.observer.collect_system_step
            apply=worker.hvac.apply
            sync=worker.hvac.synchronize_cooling

            def record_sample():
                row=observe()
                log(samples,{'decision': worker.completed if worker.phase=='control' else None, **row})
                return row

            def record_apply(action):
                value=apply(action)
                log(control,dict(kind='apply',decision=worker.completed,action=value,writes=worker.hvac.get_last_writes()))
                return value

            def record_sync():
                load=sync()
                log(control,dict(kind='predictor',decision=worker.completed,load=load,
                                 speed=worker.hvac.cooling_speed_override,writes=worker.hvac.get_last_writes()))
                return load

            worker.observer.collect_system_step=record_sample
            worker.hvac.apply=record_apply
            worker.hvac.synchronize_cooling=record_sync
            return worker

        try:
            with patch('ecobuilding.sinergym_adapter.environment.prepare_episode_inputs', reported_inputs), patch(
                    'ecobuilding.sinergym_adapter.environment.EcoBuildingSimulator', factory):
                vector, info=env.reset(seed=42,options=scenario.reset_options())
            assert env.observation_space.contains(vector)
            log(observations,dict(state=vector.tolist(),info=info))
            for index, action in enumerate(actions):
                vector,reward,terminated,truncated,info=env.step(action)
                assert env.observation_space.contains(vector) and (terminated,truncated)==(False,index==671)
                log(observations,dict(state=vector.tolist(),reward=reward,terminated=terminated,truncated=truncated,info=info))
            assert not worker.worker_alive() and worker.sim_results['exit_code']==0
            write(target/'completion.json',dict(code=0,transitions=672,observations=673,
                                               observation_dtype=str(vector.dtype), observation_shape=vector.shape))
        finally:
            env.close()
        assert worker.energyplus_state is None and not worker.worker_alive()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new directory for the five episodes")
    out = parser.parse_args().output.resolve()
    out.mkdir()
    plan=EpisodePlan.load()
    hashes={str(p.relative_to(ROOT)):digest(p) for p in (MODEL,EPW,DEFAULT_CONFIG)}
    assert tuple(STATE_NAMES) and len(STATE_NAMES)==20
    rng=Random(3885)
    choices=list(product(range(3),repeat=3))
    actions=[action for _ in range(25) for action in rng.sample(choices,len(choices))][:672]
    assert set(actions)==set(choices)
    names=(('hiver',1,27),('printemps',4,28),('ete',8,7),('automne',10,9),('hiver-rejeu',1,27))
    for name,month,day in names:
        when=date(plan.reference_year,month,day)
        assert when in plan.splits['train'].admissible_starts and 42 in plan.splits['train'].occupancy_seeds
        scenario=EpisodeScenario(when,42,plan.episode_days,plan.history_days)
        spec=dict(split='train',scenario=scenario.to_record(),reference_year=plan.reference_year,
                  history_days=7,episode_days=7,decision_interval_seconds=900,
                  occupancy_mode='dynamic',gym_seed=42,action_rng_seed=3885,hashes=hashes)
        execute(out,name,spec,actions)
        print(name, '672 transitions, fin naturelle',flush=True)
    assert hashes=={str(p.relative_to(ROOT)):digest(p) for p in (MODEL,EPW,DEFAULT_CONFIG)}


if __name__=='__main__':
    main()
