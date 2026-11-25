# Épisodes et ensembles météorologiques du MDP

La [configuration validée](../configs/rl/office_mdp.json) définit des épisodes de sept jours contrôlés après sept jours de préparation. Le pas est de 900 secondes, soit 672 transitions par épisode. L’occupation est dynamique. Le facteur `gamma=0.99` est destiné au futur algorithme RL. Il n’entre pas dans la récompense ni dans les arguments de `EcoBuildingEnv.reset`.

Les dates utilisent le couple mois/jour de l’EPW Belfort–Fontaine. L’année synthétique 2006 sert au calcul des jours de semaine, avec un dimanche au 1er janvier et sans 29 février. Elle ne désigne pas l’année d’origine des relevés de l’EPW. Le jour transmis à `Episode.start_day` est celui du premier jour de préparation. Un même jour météorologique conserve ainsi le même jour de semaine d’un scénario à l’autre.

## Départs admissibles

Toutes les bornes du tableau sont inclusives. `D` désigne le premier jour de contrôle. Le bloc utilisé va de `D−7` à `D+6`. Une fenêtre doit rester dans son ensemble et satisfaire les contraintes de l’adaptateur, notamment aux limites de l’année et au passage de fin février.

| Ensemble | Blocs météo | Départs de contrôle |
|---|---|---|
| Train | 16/01–28/02, 01/03–05/04, 21/04–17/05, 12/06–15/08, 10/09–16/11, 17/12–31/12 | 23/01–22/02, 08/03–30/03, 28/04–11/05, 19/06–09/08, 17/09–10/11, 24/12–25/12 |
| Validation | 18/05–11/06, 17/11–16/12 | 25/05–05/06, 24/11–10/12 |
| Test | 01/01–15/01, 06/04–20/04, 16/08–09/09 | 08/01–09/01, 13/04–14/04, 23/08–03/09 |

| Ensemble | Jours météo | Départs admissibles |
|---|---:|---:|
| Train | 255 (69,86 %) | 177 (79,73 %) |
| Validation | 55 (15,07 %) | 29 (13,06 %) |
| Test | 55 (15,07 %) | 16 (7,21 %) |

Les 365 jours participent à au moins une fenêtre, dont certains uniquement pendant la préparation. Il existe 222 dates de départ au total. Les fenêtres peuvent se chevaucher dans un ensemble, ce qui limite l’indépendance statistique des épisodes.

## Manifeste commun aux futurs lots RBC et PPO

Le tirage train parcourt les seeds d’occupation 0 à 199 dans l’ordre. `random.Random(380803)` choisit un départ parmi les dates triées pour chaque seed, avec remise. La validation associe les seeds 10000 à 10005 aux six dates fixes du JSON, dans l’ordre. Le test associe les seeds 20000 à 20009 de la même manière à dix dates fixes. Les manifestes d’évaluation n’utilisent aucun tirage.

Depuis la racine, dans l’environnement Python du projet avec `src` sur `PYTHONPATH`, créer les fichiers dans un dossier de sortie existant.

```python
from pathlib import Path
from ecobuilding.episodes import EpisodePlan

plan = EpisodePlan.load()
output = Path("simulation-outputs/office-mdp")
output.mkdir(parents=True, exist_ok=True)
for split in ("train", "validation", "test"):
    plan.write_manifest(split, output / f"{split}.json")
```

`write_manifest` refuse d’écraser un fichier existant. Utiliser le même fichier de validation ou de test avec les deux agents. Le plan vérifie la métadonnée, la date, la seed et le jour de semaine lors de la lecture. La relecture train utilise les dates stockées plutôt qu’un nouveau tirage.

```python
scenarios = plan.load_manifest(output / "validation.json")
# Plus tard, dans chaque évaluation avec un EcoBuildingEnv déjà construit :
# for scenario in scenarios:
#     observation, info = env.reset(options=scenario.reset_options())
```

Premier enregistrement de validation.

```json
{"control_start": "05-25", "start_day": "Thursday", "occupancy_seed": 10000}
```
