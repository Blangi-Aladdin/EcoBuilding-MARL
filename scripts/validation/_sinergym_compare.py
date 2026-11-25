"""Compare homologous native and API observations without realigning or interpolating."""
from collections import Counter, defaultdict
import csv
from datetime import datetime
from hashlib import sha256
import json
from math import isclose, sqrt
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

METER="Electricity:Facility [J](TimeStep)"


def csv_rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def jsonl(path):
    return [json.loads(s) for s in path.read_text().splitlines()]


def write_csv(path,rows,fields=None):
    if not rows and not fields:
        return
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0])); w.writeheader(); w.writerows(rows)


def sha(path):
    return sha256(path.read_bytes()).hexdigest()


def native_date(row):
    end=datetime.fromisoformat(row["time"]["end"])
    start=datetime.fromisoformat(row["time"]["start"])
    clock="24:00:00" if end.date()!=start.date() else end.strftime("%H:%M:%S")
    return [start.strftime("%m/%d"),clock]


class Comparison:
    def __init__(self, name, times):
        self.name=name
        self.times=times
        self.stats={}
        self.errors=[]
        self.structural=[]

    def stamp(self, index):
        return self.times[index-1] if isinstance(index,int) and 1<=index<=len(self.times) else ""

    def discrete(self,key,a,b,index):
        if a!=b:
            self.errors.append(dict(case=self.name,field=key,index=index,date=self.stamp(index),reference=repr(a),
                               sinergym=repr(b),kind="discret/structure"))

    def number(self,key,a,b,index):
        if any(x is None or type(x) is bool for x in (a,b)):
            self.discrete(key,a,b,index)
            return
        a,b=float(a),float(b)
        error=abs(a-b)
        rec=self.stats.setdefault(key,dict(case=self.name,field=key,values=0,exact=0,different=0,
            max_abs=0.0,abs_mean=0.0,mae=0.0,rmse=0.0,max_rel=0.0,first_index="",first_date="",out_of_tol=0))
        rec["values"]+=1
        rec["abs_mean"]+=error
        rec["rmse"]+=error*error
        rec["max_abs"]=max(rec["max_abs"],error)
        if a:
            rec["max_rel"]=max(rec["max_rel"],error/abs(a))
        if error:
            if not rec["different"]:
                rec["first_index"]=index
                rec["first_date"]=self.stamp(index)
            rec["different"]+=1
            if not isclose(a,b,abs_tol=ABS,rel_tol=REL):
                rec["out_of_tol"]+=1
                self.errors.append(dict(case=self.name,field=key,index=index,date=self.stamp(index),
                                        reference=a,sinergym=b,kind="numerique hors tolerance"))
        else:
            rec["exact"]+=1

    def tree(self,key,a,b,index):
        if isinstance(a,dict) and isinstance(b,dict):
            self.discrete(key+".keys",set(a),set(b),index)
            for k in a.keys() & b.keys():
                self.tree(f"{key}.{k}",a[k],b[k],index)
        elif isinstance(a,list) and isinstance(b,list):
            self.discrete(key+".length",len(a),len(b),index)
            for x,y in zip(a,b):
                self.tree(key+"[]",x,y,index)
        elif type(a) is float and type(b) in (int,float) or type(b) is float and type(a) in (int,float):
            self.number(key,a,b,index)
        else:
            self.discrete(key,a,b,index)

    def metrics(self):
        for rec in self.stats.values():
            rec["abs_mean"]/=rec["values"]
            rec["mae"]=rec["abs_mean"]
            rec["rmse"]=sqrt(rec["rmse"]/rec["values"])
        return list(self.stats.values())


def samples_group(rows):
    result=defaultdict(list)
    for row in rows:
        row=dict(row)
        step=int(row.pop("step"))
        result[step].append({k:(float(v) if isinstance(v,str) and v else None if v=="" else v)
                            for k,v in row.items()})
    return result



def check_steps(comp, prefix, side, rows, last_step):
    """Check the raw callback order before grouping records by zone step."""
    previous = 0
    counts = Counter()
    for row in rows:
        step = int(row["step"])
        if not 1 <= step <= last_step:
            comp.discrete(f"{prefix}.step_range.{side}", f"1..{last_step}", step, step)
        if step < previous:
            comp.discrete(f"{prefix}.step_order.{side}", f">={previous}", step, step)
        counts[step] += 1
        previous = step
    return counts


def check_hvac_endpoints(comp, side, groups):
    """Finalized reports are unique and ordered by end time within each zone step."""
    for step, samples in groups.items():
        seen = set()
        previous = None
        for sample in samples:
            end = sample["end_seconds"]
            if end in seen:
                comp.discrete(f"hvac.duplicate.{side}", "unique (step, end_seconds)", (step, end), step)
            elif previous is not None and end < previous:
                comp.discrete(f"hvac.end_order.{side}", f">={previous}", end, step)
            seen.add(end)
            previous = end

def indicators(rows):
    s={}
    fields={
        "temperature_c":("indoor","indoor_c"),"humidity_pct":("indoor","indoor_rh_pct"),
        "co2_ppm":("indoor","co2_ppm"),"heat_w":("equipment","heat_electric_w"),
        "dx_thermal_w":("equipment","dx_total_w"),"dx_electrical_w":("equipment","dx_electric_w"),
        "vent_m3_h":("equipment","vent_m3_h"),
    }
    for name,(group,key) in fields.items():
        values=[o[group][key] for o in rows]
        s[name]=dict(min=min(values),max=max(values),mean=sum(values)/len(values))
    s["people_hours"]=sum(o["occupancy"]["people"] for o in rows)/4
    s["occupied_steps"]=sum(o["occupancy"]["presence"] for o in rows)
    s["simultaneous_heat_dx_steps"]=sum(o["equipment"]["heating_active"] and o["equipment"]["dx_active"] for o in rows)
    s["energy_j"]={key:sum(o["energy"][key] for o in rows)
                   for key in ("heating_j","cooling_dx_j","ventilation_j","total_j")}
    return s


def seasonal_figure(name, direct, sim):
    x=np.arange(len(direct))/96
    def values(rows):
        return [
            [o["indoor"]["indoor_c"] for o in rows], [o["outdoor"]["outdoor_c"] for o in rows],
            [o["indoor"]["indoor_rh_pct"] for o in rows], [o["indoor"]["co2_ppm"] for o in rows],
            [o["occupancy"]["people"] for o in rows], [o["equipment"]["heat_electric_w"] for o in rows],
            [o["equipment"]["dx_total_w"] for o in rows], [o["equipment"]["vent_m3_h"] for o in rows],
            np.cumsum([o["energy"]["total_kwh"] for o in rows]), [len(o["time"]["hvac_seconds"]) for o in rows],
        ]
    a,b=np.asarray(values(direct)),np.asarray(values(sim))
    labels=("Temp. intérieure [°C]","Temp. extérieure [°C]","HR fin zone [%]","CO₂ fin zone [ppm]",
            "Occupation [pers.]","Chauffage [W]","Froid DX [W]","Air neuf [m³/h]","Cumul [kWh]","Sous-pas HVAC")
    fig,ax=plt.subplots(5,2,figsize=(13,12),sharex=True,layout="constrained")
    fig.suptitle(name + (" · superposition exacte" if np.array_equal(a,b) else " · comparaison au pas de zone"),weight="bold")
    for axis,label,ref,test in zip(ax.flat,labels,a,b):
        axis.plot(x,ref,label="Direct 36.7",linewidth=1.5)
        axis.plot(x,test,label="Sinergym",linewidth=1,linestyle="--")
        axis.set_ylabel(label)
        axis.grid(alpha=.2)
    ax.flat[0].legend()
    for axis in ax[-1]:
        axis.set_xlabel("Jours contrôlés")
    fig.savefig(OUT/"graphiques"/f"{name}.png",dpi=140)
    plt.close(fig)
    maxima=np.max(np.abs(a-b),axis=1)
    fig,ax=plt.subplots(figsize=(10,5),layout="constrained")
    ax.barh(labels,maxima)
    ax.set(xlabel="Écart absolu maximal dans l’unité du champ",title=f"{name} · écarts maximaux")
    if not np.any(maxima):
        ax.set_xlim(0,1)
        ax.text(.5,.5,"Tous les écarts sont nuls",ha="center",transform=ax.transAxes)
    fig.savefig(OUT/"graphiques"/f"{name}-ecarts.png",dpi=140)
    plt.close(fig)


def compare_case(name, plot=True):
    reference=history/name
    actual=OUT/"sinergym"/name
    execution=json.loads((actual/"execution.json").read_text())
    output=OUT/"sinergym/episodes"/Path(execution["output_path"]).parent.name/"output"
    model=output.parent/"office_1zone.epJSON"
    ref_model=reference/"office_1zone.epJSON"
    assert json.loads(model.read_text())==json.loads(ref_model.read_text())
    a=jsonl(reference/"observations.jsonl")
    b=jsonl(actual/"observations.jsonl")
    comp=Comparison(name,[o["time"]["start"] for o in a])
    comp.discrete("zone.length",len(a),len(b),0)
    hvac_direct = csv_rows(reference/"mesures-sous-pas.csv")
    hvac_sinergym = jsonl(actual/"mesures-sous-pas.jsonl")
    comp.discrete("hvac.count", len(hvac_direct), len(hvac_sinergym), 0)
    check_steps(comp, "hvac", "direct", hvac_direct, len(a))
    check_steps(comp, "hvac", "sinergym", hvac_sinergym, len(b))
    samples_a = samples_group(hvac_direct)
    samples_b = samples_group(hvac_sinergym)
    comp.discrete("hvac.step_groups", sorted(samples_a), sorted(samples_b), 0)
    check_hvac_endpoints(comp, "direct", samples_a)
    check_hvac_endpoints(comp, "sinergym", samples_b)

    groups=[r for r in csv_rows(reference/"chronologie.csv") if r["phase"]=="after_predictor"]
    predictors=jsonl(actual/"predicteur.jsonl")
    comp.discrete("predictor.count",len(groups),len(predictors),0)
    counts_a = check_steps(comp, "predictor", "direct", groups, len(a))
    counts_b = check_steps(comp, "predictor", "sinergym", predictors, len(b))
    comp.discrete("predictor.step_groups", sorted(counts_a), sorted(counts_b), 0)
    for step in sorted(counts_a.keys() | counts_b.keys()):
        comp.discrete("predictor.step_count", counts_a[step], counts_b[step], step)
    for p,q in zip(groups,predictors):
        step=int(p["step"])
        comp.discrete("predictor.step",step,q["step"],step)
        comp.number("predictor.load_w",p["load_w"],q["load_w"],step)
        comp.discrete("predictor.speed_override",int(p["speed_override"]),q["speed_override"],step)
    for index,(p,q) in enumerate(zip(a,b),1):
        comp.tree("zone",p,q,index)
        sa,sb=samples_a[index],samples_b[index]
        if len(sa)!=len(sb):
            comp.structural.append(dict(case=name,step=index,date=comp.stamp(index),direct=len(sa),sinergym=len(sb)))
            comp.discrete("hvac.substep_count",len(sa),len(sb),index)
        for side,samples in (("direct",sa),("sinergym",sb)):
            comp.number(f"hvac.duration_vs_900.{side}",900,sum(r["seconds"] for r in samples),index)
        if len(sa)==len(sb):
            for x,y in zip(sa,sb):
                comp.discrete("hvac.stage",x["dx_speed_level"],y["dx_speed_level"],index)
                for k in x:
                    comp.number("hvac."+k,x[k],y[k],index)
    ref_csv,sim_csv=reference/"eplusout.csv",output/"eplusout.csv"
    native_a,native_b=csv_rows(ref_csv),csv_rows(sim_csv)
    comp.discrete("csv.columns",list(native_a[0]),list(native_b[0]),0)
    comp.discrete("csv.rows",len(native_a),len(native_b),0)
    csv_same=sha(ref_csv)==sha(sim_csv)
    zones_seen=0
    zones_history=len([r for r in native_a if r[METER]])-len(a)
    # Compare native units and frequencies by using the full column headers.
    # A byte-identical CSV proves exact equality for blank and text cells too.
    if csv_same:
        for column in native_a[0]:
            values=0
            for row in native_a:
                value=row[column]
                if not value:
                    continue
                try:
                    float(value)
                except ValueError:
                    continue
                values+=1
            if values:
                comp.stats["csv."+column]=dict(case=name,field="csv."+column,values=values,
                    exact=values,different=0,max_abs=0.0,abs_mean=0.0,mae=0.0,rmse=0.0,
                    max_rel=0.0,first_index="",first_date="",out_of_tol=0)
    else:
        for p,q in zip(native_a,native_b):
            zones_seen+=bool(p[METER])
            index=zones_seen-zones_history
            for k in p.keys() & q.keys():
                x,y=p[k],q[k]
                try:
                    x,y=float(x),float(y)
                except (ValueError,TypeError):
                    comp.discrete("csv."+k,x,y,index)
                else:
                    comp.number("csv."+k,x,y,index)
    facility_a=[row for row in native_a if row[METER]]
    facility_b=[row for row in native_b if row[METER]]
    init=json.loads((actual/"observation-initiale.json").read_text())["info"]["physical"]
    init_csv=facility_a[-len(a)-1]
    comp.discrete("initial.history.csv_time",init_csv["Date/Time"].split(),native_date(init),0)
    for k in ("indoor_c","indoor_rh_pct","co2_ppm","people"):
        name_map={"indoor_c":"Zone Mean Air Temperature","indoor_rh_pct":"Zone Air Relative Humidity",
                  "co2_ppm":"Zone Air CO2 Concentration","people":"Zone People Occupant Count"}
        col=next(c for c in init_csv if c.upper().startswith(("OFFICE:"+name_map[k]+" [").upper()) and "(TimeStep)" in c)
        src=init["diagnostics"]["substep_means"] if k in ("indoor_rh_pct","co2_ppm") else init["diagnostics"]["api_zone_end"]
        comp.number("initial.history."+k,init_csv[col],src[k],0)
    comp.number("initial.history.total_j",init_csv[METER],init["energy"]["total_j"],0)
    for index,(p,q,x,y) in enumerate(zip(a,b,facility_a[-len(a):],facility_b[-len(b):]),1):
        comp.discrete("facility.time.reference",x["Date/Time"].split(),native_date(p),index)
        comp.discrete("facility.time.sinergym",y["Date/Time"].split(),native_date(q),index)
        comp.number("facility.direct_vs_sinergym",x[METER],y[METER],index)
        comp.number("facility.direct_api_csv",x[METER],p["energy"]["total_j"],index)
        comp.number("facility.sinergym_api_csv",y[METER],q["energy"]["total_j"],index)
    daily=[]
    for day in range(len(a)//96):
        for k in ("heating_j","cooling_dx_j","ventilation_j","total_j"):
            d=sum(o["energy"][k] for o in a[96*day:96*(day+1)])
            s=sum(o["energy"][k] for o in b[96*day:96*(day+1)])
            comp.number("daily."+k,d,s,96*day+1)
            daily.append(dict(case=name,date=a[96*day]["time"]["start"][:10],item=k,direct_j=d,sinergym_j=s,delta_j=s-d))
    stats_a,stats_b=indicators(a),indicators(b)
    comp.tree("indicators",stats_a,stats_b,0)
    assert "0 Warning; 0 Severe Errors" in (output/"eplusout.end").read_text()
    status="divergence" if comp.errors else "exact" if all(not r["different"] for k,r in comp.stats.items()
                   if k.startswith(("zone.","predictor.","hvac.")) and "duration_vs_900" not in k) else "equivalent"
    table=dict(case=name,reference=str(reference.relative_to(ROOT)),type="historique",steps=len(a),
               substeps_direct=sum(map(len,samples_a.values())),substeps_sinergym=sum(map(len,samples_b.values())),
               max_temp=comp.stats.get("zone.indoor.indoor_c",{}).get("max_abs",0),
               max_rh=comp.stats.get("zone.indoor.indoor_rh_pct",{}).get("max_abs",0),
               max_co2=comp.stats.get("zone.indoor.co2_ppm",{}).get("max_abs",0),
               max_energy_j=comp.stats.get("zone.energy.total_j",{}).get("max_abs",0),
               delta_total_j=stats_b["energy_j"]["total_j"]-stats_a["energy_j"]["total_j"],
               total_reference_kwh=stats_a["energy_j"]["total_j"]/3_600_000,
               occupancy_differences=sum(p["occupancy"]!=q["occupancy"] for p,q in zip(a,b)),
               action_differences=sum(p["actions"]!=q["actions"] for p,q in zip(a,b)),
               csv_identical=csv_same,csv_sha_direct=sha(ref_csv),csv_sha_sinergym=sha(sim_csv),
               model_sha_direct=sha(ref_model),model_sha_sinergym=sha(model),status=status)
    (OUT/"comparaisons"/(name+"-indicateurs.json")).write_text(json.dumps(
        dict(reference=stats_a,sinergym=stats_b,initial=init),indent=2)+"\n")
    if plot and name.startswith("long-"):
        seasonal_figure(name,a,b)
    return table,comp.metrics(),comp.errors,comp.structural,daily


def main():
    global ROOT, OUT, ABS, REL, history
    ROOT, OUT = map(Path, sys.argv[1:3])
    settings = json.loads((OUT / "audit/tolerances.json").read_text())
    ABS, REL = settings["abs_tol"], settings["rel_tol"]
    history = OUT / "reproductions-directes"
    names=[r["case"] for r in csv_rows(OUT/"audit/inventaire-36.7.csv") if r["category"] in ("A","B")]
    summary,metrics,errors,structural,daily=[],[],[],[],[]
    for name in names:
        if not (OUT/"sinergym"/name/"execution.json").exists():
            print("Missing run:",name)
            continue
        result=compare_case(name)
        summary.append(result[0]); metrics+=result[1]; errors+=result[2]; structural+=result[3]; daily+=result[4]
        print(name,result[0]["status"],len(result[2]),flush=True)
    target=OUT/"comparaisons"
    write_csv(target/"scenarios.csv",summary)
    write_csv(target/"metriques.csv",metrics)
    write_csv(target/"divergences.csv",errors,["case","field","index","date","reference","sinergym","kind"])
    write_csv(target/"subdivisions-divergentes.csv",structural,["case","step","date","direct","sinergym"])
    write_csv(target/"energie-journaliere.csv",daily)
    print(f"{len(summary)}/{len(names)} compatible cases evaluated, {len(errors)} divergences")
    sys.exit(bool(errors) or len(summary)!=len(names))


if __name__ == "__main__":
    main()
