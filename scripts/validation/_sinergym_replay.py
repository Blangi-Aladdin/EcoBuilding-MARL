"""Reproduce physically homologous histories with the unmodified adapter."""
import csv
from functools import wraps
import json
from pathlib import Path
import resource
import sys
from time import monotonic
from unittest.mock import patch

from pyenergyplus.runtime import Runtime
from sinergym.simulators.eplus import EnergyPlus
from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode
from ecobuilding.sinergym_adapter.environment import prepare_episode_inputs
from ecobuilding.sinergym_adapter.simulator import EcoBuildingSimulator
import gymnasium as gym

def main():
    ROOT, OUT = map(Path,sys.argv[1:3])
    REF=OUT/"reproductions-directes"
    configuration=json.loads((OUT/"audit/execution-inputs.json").read_text())
    MODEL=ROOT/configuration["model"]
    EPW=ROOT/configuration["weather"]
    assert EcoBuildingSimulator.start is EnergyPlus.start
    with (OUT/"audit/inventaire-36.7.csv").open() as f:
        inventory=list(csv.DictReader(f))
    order=["long-winter","long-summer","long-autumn"]+[r["case"] for r in inventory
            if r["category"] in ("A","B") and not r["case"].startswith("long-")]
    if len(sys.argv)>3:
        order=sys.argv[3:]
    env=EcoBuildingEnv(MODEL,EPW,OUT/"sinergym/episodes",Episode((12,17),days=7),
                       cooling_setpoint_c=configuration["cooling_setpoint_c"])


    def dump(path, data):
        path.write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")


    def replay(name):
        path=OUT/"sinergym"/name
        path.mkdir()
        spec=json.loads((OUT/"references-historiques"/f"{name}.json").read_text())
        reference=json.loads((REF/name/"office_1zone.epJSON").read_text())
        worker=None
        results=[]
        engine_codes=[]
        runtime_paths=[]

        def prepare(*args,**kwargs):
            model,epw,output=prepare_episode_inputs(*args,**kwargs)
            copy=json.loads(model.read_text())
            delta={k for k in set(copy)|set(reference) if copy.get(k)!=reference.get(k)}
            assert delta <= {"Output:Meter","Output:Variable"},delta
            dump(path/"entrees.json",dict(epw=str(epw),initial_copy_diff=sorted(delta),
                                        physical_equal=True,output_path=str(output),reference=str(REF/name)))
            for key in delta:
                copy[key]=reference[key]
            assert copy==reference
            model.write_text(json.dumps(copy,indent=2)+"\n")
            runtime_paths.append(output)
            return model,epw,output

        with (path/"mesures-sous-pas.jsonl").open("w") as raw, (path/"predicteur.jsonl").open("w") as predictor, (path/"observations.jsonl").open("w") as obs:
            def instrument(*args,**kwargs):
                nonlocal worker
                worker=EcoBuildingSimulator(*args,**kwargs)
                runtime=worker.api.runtime._runtime
                assert type(runtime) is Runtime
                run=runtime.run_energyplus
                def native(state,arguments):
                    code=run(state,arguments)
                    engine_codes.append(code)
                    return code
                runtime.run_energyplus=native
                collect=worker.observer.collect_system_step
                def sample():
                    reading=collect()
                    if worker.phase=="control":
                        raw.write(json.dumps(dict(step=worker.completed+1,**reading),allow_nan=False)+"\n")
                    return reading
                worker.observer.collect_system_step=sample
                sync=worker.hvac.synchronize_cooling
                def synchronize():
                    load=sync()
                    predictor.write(json.dumps(dict(step=worker.completed+1,load_w=load,
                        speed_override=worker.hvac.cooling_speed_override),allow_nan=False)+"\n")
                    return load
                worker.hvac.synchronize_cooling=synchronize
                return worker

            try:
                options={"episode":Episode(tuple(spec["first"]),days=spec["days"],
                         history_days=spec["history_days"],start_day=spec["start_day"])}
                if spec["profile"] is not None:
                    options.update(occupancy_mode="explicit",occupancy_profile=spec["profile"])
                start=monotonic()
                with patch("ecobuilding.sinergym_adapter.environment.EcoBuildingSimulator",instrument), patch(
                        "ecobuilding.sinergym_adapter.environment.prepare_episode_inputs",prepare):
                    vector,init=env.reset(seed=configuration["gym_seed"],options=options)
                after_reset=monotonic()
                dump(path/"observation-initiale.json",dict(info=init,projection=vector.tolist()))
                end=init["end"]
                for index,action in enumerate(spec["actions"]):
                    vector,reward,terminated,truncated,info=env.step(action)
                    assert info["decision_id"]==index and info["start"]==end
                    assert info["applied"]==tuple(action)==info["requested"]
                    assert info["physical"]["occupancy"]["people"]==spec["expected_people"][index]
                    assert (reward,terminated,truncated)==(0.0,False,index==len(spec["actions"])-1)
                    obs.write(json.dumps(info["physical"],allow_nan=False)+"\n")
                    end=info["end"]
                after_last=monotonic()
                assert engine_codes==[0] and not worker.worker_alive()
                try:
                    env.step((0,0,0))
                except gym.error.ResetNeeded:
                    pass
                else:
                    raise AssertionError("Extra step accepted")
            finally:
                env.close()
            assert worker.energyplus_state is None and not worker.worker_alive()
            dump(path/"execution.json",dict(steps=index+1,exit_codes=engine_codes,output_path=str(runtime_paths[0]),
                 reset_s=after_reset-start,steps_s=after_last-after_reset,cleanup_s=monotonic()-after_last,
                 peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
    for name in order:
        print(f"Replaying {name}",flush=True)
        replay(name)


if __name__ == "__main__":
    main()
