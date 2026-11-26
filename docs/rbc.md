# Contrôle à règles — Lot 3

Le lot 3 fournit une stratégie RBC saisonnière sans entraîner ni apprendre de paramètres.
Elle lit la projection MDP qualifiée, choisit un triplet Heating/Cooling/Ventilation
et conserve ses niveaux précédents pour appliquer une hystérésis.

## Contrôleur

[SeasonalRBC](../src/ecobuilding/controllers/rbc.py) utilise :

- la température intérieure agrégée du dernier pas ;
- l’effectif réel de l’intervalle ;
- le CO₂ intérieur agrégé ;
- le mois physique du début de l’intervalle ;
- les niveaux précédemment produits par le contrôleur.

Le contrôleur accepte une observation NumPy `float32` de forme `(20,)`, comme
celle de `EcoBuildingEnv`, ou un dictionnaire contenant les clés de `STATE_NAMES`.
Il expose :

```python
controller.reset()
action = controller.act(observation, info)
```

`action` est toujours un triplet entier `(Heating, Cooling, Ventilation)`.

## Règles thermiques

Les bornes occupées sont celles du contrat MDP :

| Saison | Borne thermique |
|---|---|
| Hiver | 20–23 °C |
| Printemps | 20–26 °C |
| Été | 23–26 °C |
| Automne | 20–26 °C |

La politique agit avec une bande d’hystérésis de 0,5 °C par défaut :

- chauffage niveau 2 sous la borne basse moins 1,5 °C ;
- chauffage niveau 1 sous la borne basse moins 0,5 °C ;
- chauffage niveau 0 à partir de la borne basse plus 0,5 °C ;
- refroidissement niveau 1 au-dessus de la borne haute plus 0,5 °C ;
- refroidissement niveau 2 au-dessus de la borne haute plus 1,5 °C ;
- refroidissement niveau 0 en dessous de la borne haute moins 0,5 °C.

Les décisions chauffage et refroidissement sont indépendantes. Elles peuvent donc
simultanément produire des niveaux non nuls.

En inoccupation, les bornes sont 15–28 °C et la ventilation est forcée à zéro.

## Règles CO2

Le changement de ventilation en occupation utilise :

| CO₂ | Niveau |
|---|---:|
| 700 ppm ou moins | 0 |
| 800 ppm ou plus | 1 |
| 1 000 ppm ou plus | 2 |

Les seuils de sortie sont inférieurs aux seuils d’entrée :

- 700 ppm pour revenir du niveau 1 au niveau 0 ;
- 900 ppm pour revenir du niveau 2 au niveau 1.

Cette bande évite les oscillations autour des seuils.

## Configuration

La configuration qualifiée par défaut est
[configs/rbc/office_default.json](../configs/rbc/office_default.json).

Ses paramètres peuvent être chargés avec :

```python
from ecobuilding.controllers import RBCConfig, SeasonalRBC

config = RBCConfig.load("configs/rbc/office_default.json")
controller = SeasonalRBC(config)
```

Toute variante utilisée dans une campagne doit être conservée avec ses résultats.

## Évaluation

Le lanceur [scripts/run_rbc_evaluation.py](../scripts/run_rbc_evaluation.py)
utilise le plan d’épisodes existant et charge les manifestes reproductibles.
Il conserve le même manifeste pour tous les contrôleurs comparés.

Depuis le terminal Docker préparé par le guide :

```bash
run=$(mktemp -d "$repo/simulation-outputs/sinergym-runs/rbc-validation-XXXXXX")
out="/project/simulation-outputs/sinergym-runs/${run##*/}"

eb python scripts/run_rbc_evaluation.py \
  --split validation \
  --config configs/rbc/office_default.json \
  --output "$out"
```

Les sorties sont créées dans un dossier nouveau contenant :

- un résumé global ;
- un résumé par épisode ;
- les observations, actions, récompenses et diagnostics ;
- les empreintes du modèle, de la météo et du plan ;
- les paramètres RBC utilisés.

La sortie actuelle doit être créée avec `--output`. Les sorties de la campagne
restent hors Git sous `simulation-outputs/`.

Pour rejouer une liste exportée :

```bash
eb python scripts/run_rbc_evaluation.py \
  --split validation \
  --manifest /project/simulation-outputs/validation.json \
  --config configs/rbc/office_default.json \
  --output "$out"
```

## Protocole de comparaison

1. Régler les paramètres sur Train uniquement.
2. Choisir une seule configuration sur Validation.
3. Ne pas modifier la configuration après Validation.
4. Exécuter Test une seule fois pour l’évaluation finale.
5. Comparer l’énergie par poste, le confort en occupation, les dépassements
   CO₂/HR, les changements d’action et la récompense cumulée.

L’évaluation ne constitue pas une qualification physique complète du modèle.
Elle fournit une base déterministe RBC appariée aux futurs contrôleurs PPO et MARL.
