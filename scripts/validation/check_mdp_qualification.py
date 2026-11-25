"""Independently check the recorded MDP against raw samples and native output."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import product
import json
from math import cos, sin, pi, fsum
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import numpy as np

from checks import col, equal, from_observation, read
from ecobuilding.occupancy_profiles import generate
from ecobuilding.observations import VARIABLES

NAMES=('hiver','printemps','ete','automne','hiver-rejeu')
TERMS=('energy','temperature','co2','humidity','action_change')
METER='Electricity:Facility [J](TimeStep)'
TEMPS={12:(20,23),1:(20,23),2:(20,23),3:(20,26),4:(20,26),5:(20,26),
       6:(23,26),7:(23,26),8:(23,26),9:(20,26),10:(20,26),11:(20,26)}
SEASON=('winter','winter','spring','spring','spring','summer','summer','summer','autumn','autumn','autumn','winter')


def jlines(path):
    return list(map(json.loads,path.read_text().splitlines()))


def engine(case):
    files=list(case.rglob('eplusout.csv'))
    assert len(files)==1
    return files[0].parent


def boundary(hours):
    angle=2*pi*hours
    return [sin(angle),cos(angle)]


def violation(x, limits):
    low,high=limits
    if x < low:
        return low-x
    if x > high:
        return x-high
    return 0.


def check(root, name):
    case=root/name
    manifest=json.loads((case/'manifest.json').read_text())
    assert manifest['split']=='train' and manifest['scenario']['occupancy_seed']==42
    actions=json.loads((case/'actions.json').read_text())
    assert set(Counter(map(tuple,actions)).values())=={24,25}
    assert set(map(tuple,actions))==set(product(range(3),repeat=3))
    records=jlines(case/'observations.jsonl')
    assert len(records)==673 and len(actions)==672
    completion=json.loads((case/'completion.json').read_text())
    assert completion==dict(code=0,transitions=672,observations=673,observation_dtype='float32',observation_shape=[20])
    samples=defaultdict(list)
    for row in jlines(case/'substeps.jsonl'):
        samples[row['decision']].append(row)
    controls=defaultdict(list)
    for row in jlines(case/'control.jsonl'):
        controls[row['decision']].append(row)
    assert samples.keys()=={None,*range(672)} and controls.keys()==set(range(672))
    native=engine(case)
    assert '0 Warning; 0 Severe Errors' in (native/'eplusout.end').read_text()
    assert '**  Fatal  **' not in (native/'eplusout.err').read_text()
    rows=read(native/'eplusout.csv')
    columns={k:col(rows,v) for k,v in VARIABLES.items()}
    rows=[row for row in rows if row[METER]]
    assert len(rows)==1344
    csv_rows=rows[-673:]
    previous_temp=previous_action=previous_end=None
    errors=defaultdict(float)
    readings=[]
    effective=Counter()

    def match(key,a,b):
        try:
            equal(a,b)
        except AssertionError as exc:
            raise AssertionError((name,index,key,a,b)) from exc
        errors[key]=max(errors[key],abs(a-b))

    for index,(record,row) in enumerate(zip(records,csv_rows,strict=True),start=-1):
        initial=index==-1
        info=record['info']
        raw=info['physical']
        start,end=map(datetime.fromisoformat,(info['start'],info['end']))
        if initial:
            assert (end.strftime('%m-%d'),end.hour,end.minute)==(manifest['scenario']['control_start'],0,0)
            assert info['requested'] is info['applied'] is None and 'reward' not in info
            expected_profile=generate(42,days=7,start_weekday=end.replace(year=manifest['reference_year']).weekday())
        else:
            assert start==previous_end and info['decision_id']==index
            assert info['requested']==info['applied']==raw['actions']['active_action']==actions[index]
            assert not record['terminated'] and record['truncated']==(index==671)
        assert (end-start)==timedelta(seconds=900)
        csv_time=f'{start:%m/%d}  '+('24:00:00' if end.date()!=start.date() else end.strftime('%H:%M:%S'))
        assert row['Date/Time'].strip()==csv_time,(name,index,csv_time,row['Date/Time'])
        substeps=samples[None if initial else index]
        match('duration_s',fsum(s['seconds'] for s in substeps),900)
        averages={k:fsum(s[k]*s['seconds'] for s in substeps)/900
                  for k in ('indoor_c','indoor_rh_pct','co2_ppm')}
        for key,value in averages.items():
            match('weighted.'+key,raw['diagnostics']['substep_means'][key],value)
        for key,column in columns.items():
            if column:
                api,_=from_observation(raw,key,substeps)
                match('csv.'+key,api,float(row[column]))
        power={k:float(row[columns[k]]) for k in ('heat_electric_w','dx_electric_w')}
        energies=[float(row[columns['heat_j']]),power['dx_electric_w']*900,float(row[columns['vent_j']])]
        for key,value in zip(('heating_j','cooling_dx_j','ventilation_j'),energies,strict=True):
            match('energy.'+key,raw['energy'][key],value)
        match('energy.dx_coil_fan_j',energies[1],float(row[columns['dx_coil_j']])+float(row[columns['dx_fan_j']]))
        total=float(row[METER])
        match('energy.facility_j',raw['energy']['total_j'],total)
        match('energy.sum_vs_facility_j',fsum(energies),total)

        outdoor=[float(row[columns[k]]) for k in ('outdoor_c','outdoor_rh_pct','direct_solar_w_m2',
                                                 'diffuse_solar_w_m2','wind_m_s')]
        people=int(float(row[columns['people']]))
        assert people==raw['occupancy']['people']
        synthetic=end.replace(year=manifest['reference_year'])
        start_weekday=start.replace(year=manifest['reference_year']).weekday()
        assert raw['time']['weekday_api']==(start_weekday+1)%7+1
        state=[*averages.values(),*outdoor,people,*boundary((end.hour+end.minute/60)/24),
               *boundary(synthetic.weekday()/7),*boundary((synthetic.timetuple().tm_yday-1)/365)]
        temp, humidity, co2=averages.values()
        if initial:
            state += [0]*5
        else:
            assert people==expected_profile[index]
            h,c,v=actions[index]
            state += [h,c,v,temp-previous_temp,total/3_600_000]
            trace=controls[index]
            requests=[event for event in trace if event['kind']=='apply']
            assert (len(requests)==1)==(previous_action!=actions[index])
            if requests:
                assert requests[0]['action']==actions[index]
                writes={write[1]:write[2:] for write in requests[0]['writes']}
                match('actuator.heating',writes['OFFICE HEATING POWER FRACTION'][0],h/2)
                match('actuator.ventilation',writes['BALANCED OUTDOOR AIR'][0],(0,40,120)[v]/3600)
                match('actuator.dx_available',writes['DX SCHEDULED AVAILABILITY'][0],int(c>0))
                if c:
                    match('actuator.dx_setpoint',writes['SUMMER COOLING SETPOINT'][0],25)
            predictions=[event for event in trace if event['kind']=='predictor']
            assert predictions and all(event['speed']==(c if event['load']<0 else 0) for event in predictions)
            assert set(raw['equipment']['dx_speed_when_cooling']) <= ({c} if c else set())
            match('physics.heating_w',power['heat_electric_w'],1000*h)
            match('physics.vent_m3_h',raw['equipment']['vent_m3_h'],(0,40,120)[v])
            if not c:
                match('physics.off_dx_j',energies[1],0)
            effective[(bool(c), raw['equipment']['dx_active'])]+=1

            occupied=people>0
            limits=TEMPS[start.month] if occupied else (15,28)
            delta_action=0 if previous_action is None else sum(abs(x-y) for x,y in zip(actions[index],previous_action))
            terms=[total/3_600_000,violation(temp,limits)/5,
                   max(0,co2-1000)/1000 if occupied else 0,
                   violation(humidity,(40,60))/20 if occupied else 0,delta_action/6]
            weights=[1,3 if occupied else 0.5,2,0.1,0.05]
            values=[x*y for x,y in zip(terms,weights,strict=True)]
            detail=info['reward']
            constraints=detail['constraints']
            assert constraints == dict(season=SEASON[start.month-1],occupied=occupied,occupants=people,
                temperature_c=list(limits),co2_max_ppm=1000 if occupied else None,
                relative_humidity_pct=[40,60] if occupied else None,temperature_weight=weights[1])
            for key,x,y in zip(TERMS,terms,values,strict=True):
                match('reward.component.'+key,detail['components'][key],x)
                match('reward.weighted.'+key,detail['weighted'][key],y)
            match('reward.total',record['reward'],-fsum(values))
            assert record['reward']==detail['total']
            readings.append(dict(temp=temp,rh=humidity,co2=co2,people=people,reward=record['reward'],
                       energy=energies,weighted=values,temp_violation=terms[1]>0,
                       co2_violation=co2>1000,rh_violation=not 40<=humidity<=60))
            previous_action=actions[index]
        vector=np.asarray(record['state'],dtype=np.float32)
        expected=np.asarray(state,dtype=np.float32)
        assert vector.shape==(20,) and np.isfinite(vector).all()
        try:
            np.testing.assert_allclose(vector,expected,atol=1e-7,rtol=1e-7)
        except AssertionError as exc:
            raise AssertionError((name,index,vector,expected)) from exc
        errors['state.float32_max']=max(errors['state.float32_max'],float(np.max(np.abs(vector-expected))))
        previous_temp,previous_end=temp,end

    occupied=[r for r in readings if r['people']]
    metric=lambda seq,key: [min(r[key] for r in seq),fsum(r[key] for r in seq)/len(seq),max(r[key] for r in seq)]
    rate=lambda seq,key:100*sum(r[key] for r in seq)/len(seq)
    penalties=dict(zip(TERMS,map(fsum,zip(*(r['weighted'] for r in readings))),strict=True))
    energy=dict(zip(('heating','cooling','ventilation'),(fsum(es)/3_600_000 for es in zip(*(r['energy'] for r in readings))),strict=True))
    summary=dict(transitions=672,observations=673,energy_kwh=energy,total_kwh=fsum(energy.values()),
        temperature=metric(readings,'temp'),occupied_hours=len(occupied)/4,thermal_violation_pct=rate(readings,'temp_violation'),
        occupied_thermal_violation_pct=rate(occupied,'temp_violation'),co2_mean=metric(readings,'co2')[1],
        occupied_co2_mean=metric(occupied,'co2')[1],occupied_co2_violation_pct=rate(occupied,'co2_violation'),
        humidity=metric(readings,'rh'),occupied_humidity_mean=metric(occupied,'rh')[1],
        occupied_humidity_violation_pct=rate(occupied,'rh_violation'),
        reward_sum=fsum(r['reward'] for r in readings),reward=metric(readings,'reward'),weighted_penalties=penalties,
        errors=dict(errors),missing_columns=[k for k,v in columns.items() if v is None],warnings=0,severe=0,
        cooling=dict(requested_steps=effective[(True,False)]+effective[(True,True)],
                     effective_steps=effective[(True,True)]))
    return summary,readings


def figures(output, tables, histories):
    labels=NAMES[:4]
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,key,ylabel in zip(axes,('energy_kwh','weighted_penalties'),('Énergie électrique (kWh)','Pénalités cumulées')):
        bottom=np.zeros(4)
        for term in tables[labels[0]][key]:
            vals=np.array([tables[l][key][term] for l in labels])
            ax.bar(labels,vals,bottom=bottom,label=term)
            bottom+=vals
        ax.set_ylabel(ylabel)
        ax.legend()
    fig.suptitle('Quatre semaines Train · séquence pseudo-aléatoire commune')
    fig.savefig(output/'energie-recompense.png',dpi=140)
    plt.close(fig)
    fig,axes=plt.subplots(4,1,figsize=(10,9),sharex=True,layout='constrained')
    for name,ax in zip(labels,axes):
        series=histories[name]
        x=np.arange(len(series))/96
        ax.plot(x,[r['temp'] for r in series],color='tab:blue',lw=1,label='Température intérieure')
        ax.fill_between(x,13,39,where=[r['people']>0 for r in series],color='tab:green',alpha=.14,label='Occupation')
        ax.set_ylabel(name+' (°C)')
    axes[0].legend(loc='upper right')
    axes[-1].set_xlabel('Jours de contrôle')
    fig.savefig(output/'temperature-occupation.png',dpi=140)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episodes", type=Path, help="directory containing the five episode folders")
    parser.add_argument("--report-dir", type=Path, required=True, help="new directory for the qualification report")
    args = parser.parse_args()
    root, output = args.episodes.resolve(), args.report_dir.resolve()
    output.mkdir()
    tables,histories={},{}
    for name in NAMES:
        tables[name],histories[name]=check(root,name)
        print(name,'conforme',flush=True)
    one,two=root/'hiver',root/'hiver-rejeu'
    for f in ('manifest.json','actions.json','observations.jsonl','substeps.jsonl','control.jsonl'):
        assert (one/f).read_bytes()==(two/f).read_bytes(),f
    assert (engine(one)/'eplusout.csv').read_bytes()==(engine(two)/'eplusout.csv').read_bytes()
    (output/'resultats.json').write_text(json.dumps(tables,indent=2,allow_nan=False)+'\n')
    figures(output,tables,histories)


if __name__=='__main__':
    main()
