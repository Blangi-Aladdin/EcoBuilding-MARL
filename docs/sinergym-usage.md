# Utiliser le bureau EcoBuilding avec Sinergym

## Image et données

Utilisez l’image Docker locale `ecobuilding-marl:dev` sur Linux x86-64 ou depuis le terminal Ubuntu WSL. La vérification 37.2.7.4 a utilisé l’image `sha256:a0fde6ada0a82bd08636a09ea87dea24387b6e32da93f11b8d5968b3ca510bf4`, `linux/amd64`. Python 3.12.3, EnergyPlus 25.1.0-1c11a3d85f (API 0.2), Sinergym 3.12.2, Gymnasium 1.2.3, Stable-Baselines3 2.7.1, NumPy 2.5.5 et PyTorch 2.9.1+cpu sont les versions qualifiées.

Ces recettes réutilisent une image existante sans téléchargement. Le Dockerfile, le snapshot APT et les locks pinent les entrées de build. Une reconstruction depuis un clone est un parcours indépendant et son identité binaire avec l’image locale reste à vérifier. [Installation et build](../README.md#cloner-construire-et-ouvrir-le-projet)

Placez l’EPW extrait de l’archive Belfort–Fontaine TMYx 2011–2025 sous `models/weather/`. Comparez son empreinte avant toute qualification. L’EPW est une entrée locale hors des fichiers à versionner. [Archive météo et emplacement](../models/README.md#météo)

```bash
sha256sum models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw
# c3abc4cfd50efc65d6a7bdb7e35c3b7716489f803fc2135747833d6192e6725a
```

## Commandes Docker et chemins

Depuis la racine du checkout sous Linux ou WSL, utilisez cette fonction Bash dans le terminal courant. Les entrées montées sont le code, les scripts, les tests, les configurations et les modèles, avec accès en lecture seule. Seul le sous-répertoire local de résultats est monté en écriture sous le même chemin relatif. `/tmp` est isolé au conteneur.

```bash
repo=$(git rev-parse --show-toplevel)
mkdir -p "$repo/simulation-outputs/sinergym-runs"
eb() {
  docker run --rm --pull never --network none --read-only --tmpfs /tmp \
    --user "$(id -u):$(id -g)" \
    -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR=/tmp \
    -e PYTHONPATH=/project/src:/usr/local/EnergyPlus-25-1-0 \
    -v "$repo/src:/project/src:ro" -v "$repo/models:/project/models:ro" \
    -v "$repo/scripts:/project/scripts:ro" -v "$repo/tests:/project/tests:ro" \
    -v "$repo/configs:/project/configs:ro" \
    -v "$repo/simulation-outputs/sinergym-runs:/project/simulation-outputs/sinergym-runs" \
    -w /project ecobuilding-marl:dev "$@"
}
docker image inspect ecobuilding-marl:dev --format '{{.Id}} {{.Os}}/{{.Architecture}}'
eb python /opt/ecobuilding/check_versions.py
eb python -m pip --no-cache-dir check
eb python scripts/run_sinergym_episode.py --help
eb python scripts/run_sinergym_episode.py --validate-only
```

`PYTHONPATH` permet l’import de `ecobuilding` depuis `src/` et de `pyenergyplus` depuis le moteur installé. Les chemins du JSON sont relatifs à la racine résolue à partir du script. `--config` désigne un fichier visible dans le conteneur. L’option `--validate-only` vérifie les entrées et construit la façade sans reset ni sortie physique.

Pour une exécution physique ultérieure de la journée hivernale B (27 janvier, 7 jours préparatoires, 96 fois `[2,1,0]`), lancez la commande suivante. Les sorties sont créées dans un dossier unique avec les entrées, leurs empreintes, les versions, la seed, les actions, les observations et le bilan par poste. `summary.json` distingue fin naturelle et erreur et exclut l’amorçage de l’énergie contrôlée. Les exceptions du moteur remontent à l’appelant.

```bash
eb python scripts/run_sinergym_episode.py --config configs/simulation/sinergym_office.json
```

## Paramètres

| Paramètre Python | Type, défaut et validation |
|---|---|
| `model_path`, `weather_path`, `output_root` | Chemins obligatoires du constructeur. Le lanceur résout les chemins relatifs du JSON dans le dépôt et place les sorties sous `simulation-outputs/`. |
| `episode` | Objet `Episode` obligatoire. `first` est le couple mois/jour obligatoire. `days=1` et `history_days=7` sont des nombres de jours entiers positifs. `start_day="Monday"` désigne le jour de semaine du premier jour préparatoire. |
| `seed` et `options` | Arguments optionnels de `reset()`, défaut `None`. Seed Gymnasium non négative. `options["episode"]` permet de remplacer l’épisode pour ce reset. Le lanceur enregistre la seed réellement choisie si le JSON l’omet. |
| `occupancy_mode` | Option de reset `native` par défaut, `explicit` ou `dynamic`. |
| `occupancy_profile` | En mode explicite uniquement, un entier 0, 1 ou 2 par intervalle contrôlé. |
| `occupancy_seed` | Entier en mode dynamique. Si omis, la seed est issue du RNG Gymnasium. |
| `cooling_setpoint_c` | Réel fini, 25 °C par défaut. Doit dépasser la consigne maximale de chauffage du gestionnaire (21 °C). |
| `fields` | Séquence non vide de `Field(path, unit)`, cinq champs par défaut. Le lanceur JSON accepte les cinq champs qualifiés et permet de définir leur sélection et ordre. |
| `startup_timeout`, `transition_timeout`, `shutdown_timeout` | Secondes, valeurs finies et strictement positives. Défauts 120, 15 et 10. |
| `trace` | Booléen, False par défaut. Active une trace interne en mémoire du simulateur, sans fichier automatique. |
| `action_blocks` | Clé du lanceur uniquement. Chaque bloc contient un nombre positif de pas et une action H/C/V. Le total doit couvrir exactement l’épisode. |

Le pas physique reste fixé à quatre pas par heure. Les paramètres internes `episode_id`, `profile` et `_api` du simulateur et l’option `report_facility` du préparateur ne sont pas des paramètres de la façade.

## Exemple Python

À utiliser avec `src/` et EnergyPlus dans `PYTHONPATH`. Cet exemple ferme volontairement après la première action.

```python
from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode

env = EcoBuildingEnv(
    "models/office_1zone.epJSON",
    "models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw",
    "simulation-outputs/sinergym-runs/example",
    Episode((1, 27)),
)
try:
    observation, info = env.reset(seed=42)
    print(observation, info["end"])
    observation, reward, terminated, truncated, info = env.step([2, 1, 0])
    print(observation, reward, terminated, truncated, info["end"])
finally:
    env.close()
```

[Architecture et contrat](sinergym-architecture.md) · [Validation et qualification](sinergym-validation.md)
