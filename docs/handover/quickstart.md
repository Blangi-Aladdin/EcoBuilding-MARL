# Prise en main d’EcoBuilding-MARL

EcoBuilding-MARL simule un bureau monozone pour étudier le pilotage du chauffage, de la climatisation et de la ventilation selon la consommation électrique et le confort. EnergyPlus calcule la physique du bâtiment. L’adaptateur Sinergym expose les commandes et le MDP dans un environnement Gymnasium. Le modèle, l’adaptateur et le MDP sont qualifiés en simulation. Les stratégies RBC, PPO et MARL relèvent des lots suivants. [Rapport de transmission](handover.md)

## 1. Préparer le poste

Le parcours qualifié utilise Docker en mode conteneurs Linux, avec une image `linux/amd64`. Prévoyez Git et un terminal Bash sous Ubuntu natif ou Ubuntu dans WSL2. VS Code et Dev Containers sont facultatifs pour le parcours en ligne de commande. Pour installer Docker Engine sous Ubuntu natif, suivez le [README](../../README.md#linux-ubuntu-natif).

Sous **Windows 11**, ouvrez **PowerShell en administrateur** pour installer Ubuntu si nécessaire. Redémarrez si Windows le demande, puis ouvrez Ubuntu une première fois pour initialiser votre compte Linux.

```powershell
wsl --install -d Ubuntu
```

Dans **PowerShell**, depuis n’importe quel répertoire, vérifiez que la distribution Ubuntu est en version 2 et installez les applications absentes.

```powershell
wsl --update
wsl -l -v
winget install --id Docker.DockerDesktop --exact
winget install --id Microsoft.VisualStudioCode --exact
```

Si la distribution nommée `Ubuntu` est en version 1, exécutez `wsl --set-version Ubuntu 2` dans PowerShell. Démarrez Docker Desktop, sélectionnez les conteneurs Linux et activez l’intégration de votre distribution dans **Settings → Resources → WSL Integration**. Pour utiliser VS Code, ouvrez un nouveau PowerShell après l’installation et installez les extensions suivantes. [Procédure Windows détaillée](../../README.md#windows-11-avec-wsl2)

```powershell
code --install-extension ms-vscode-remote.remote-wsl
code --install-extension ms-vscode-remote.remote-containers
```

Dans le **terminal Ubuntu**, depuis n’importe quel répertoire, vérifiez que Docker affiche une section serveur. Si Git est absent, installez-le avec `sudo apt update` puis `sudo apt install -y git`.

```bash
git --version
docker version
```

## 2. Cloner GitHub et retrouver la version qualifiée

Dans le **terminal Ubuntu**, exécutez ces commandes pour un nouveau clone. Le commit technique de référence est `cec22b6a076da718d05f7b2bc1559c3feae9bcd0`, accessible sur la [branche des lots 1 et 2](https://github.com/Blangi-Aladdin/EcoBuilding-MARL/tree/feature/lot1-lot2-building-environment).

```bash
mkdir -p ~/projects
cd ~/projects
git clone --branch feature/lot1-lot2-building-environment https://github.com/Blangi-Aladdin/EcoBuilding-MARL.git
cd EcoBuilding-MARL
git cat-file -e 'cec22b6a076da718d05f7b2bc1559c3feae9bcd0^{commit}'
git log -1 --oneline
```

Si le commit est introuvable ou si GitHub refuse l’accès, arrêtez-vous et demandez au groupe l’accès à la référence de transmission ou un export Git. Restez sur la branche de transmission pour conserver les guides publiés. Lors de la vérification 2.4, le commit documentaire publié était `fe9dbc894bcf7e0cfff85c3303f480a200fd9e06`. Pour rejouer strictement la version technique qualifiée, utilisez au besoin `git switch --detach cec22b6a076da718d05f7b2bc1559c3feae9bcd0` dans une copie de travail dédiée. Les guides de passation ont été ajoutés après ce commit. La [capitalisation technique](technical-knowledge.md) fait partie du référentiel documentaire versionné. Le [rapport publié](handover.md#6-décisions-techniques-à-préserver) résume les contrats à préserver. Les preuves détaillées sont à récupérer séparément. [Inventaire](inventory.md#5-inventaire-des-preuves-de-validation)

## 3. Installer l’environnement et préparer la météo

Exécutez la suite depuis la **racine du dépôt dans le terminal Ubuntu**. Le Dockerfile et les fichiers `requirements*.lock` installent les dépendances dans l’image. Si l’image est absente, construisez-la avec la première commande. La deuxième permet aussi d’identifier une image déjà fournie par le groupe.

```bash
docker build --platform linux/amd64 -t ecobuilding-marl:dev .
docker image inspect ecobuilding-marl:dev --format '{{.Id}} {{.Os}}/{{.Architecture}}'
```

Versions qualifiées dans l’image locale — Python 3.12.3, EnergyPlus 25.1.0-1c11a3d85f (API 0.2), Sinergym 3.12.2, Gymnasium 1.2.3, Stable-Baselines3 2.7.1, NumPy 2.5.5 et PyTorch 2.9.1+cpu. L’identité binaire d’une reconstruction avec l’image qualifiée reste à vérifier. Pour VS Code, lancez `code .` depuis la racine puis choisissez **Dev Containers: Reopen in Container** dans la palette. [Versions et configuration Docker](../sinergym-usage.md#image-et-données) · [Dev Container](../../.devcontainer/devcontainer.json)

Téléchargez l’archive indiquée dans le [guide de validation du bureau](../validation.md). Extrayez le fichier EPW Belfort–Fontaine TMYx 2011–2025 dans `models/weather/` et conservez-le localement. Vérifiez l’empreinte du modèle et celle de l’EPW avant de poursuivre.

```bash
mkdir -p models/weather
sha256sum -c <<'HASHES'
10bb0cc672e293b3f1f82afc31a38fff38f4795c67c928ef1ffec117383b2bf3  models/office_1zone.epJSON
c3abc4cfd50efc65d6a7bdb7e35c3b7716489f803fc2135747833d6192e6725a  models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw
HASHES
```

## 4. Se repérer dans le dépôt

| Chemin | Rôle |
| --- | --- |
| [`models/`](../../models/) | Modèle physique `office_1zone.epJSON`, documentation et météo locale sous `weather/`. |
| [`src/ecobuilding/`](../../src/ecobuilding/) | Commandes HVAC, observations, occupation et exécution EnergyPlus directe. |
| [`src/ecobuilding/sinergym_adapter/`](../../src/ecobuilding/sinergym_adapter/) | Environnement Gymnasium, échanges avec EnergyPlus, état MDP et récompense. |
| [`configs/`](../../configs/) | Démonstration Sinergym, configurations de qualification et plan des épisodes MDP. |
| [`scripts/`](../../scripts/) et [`tests/`](../../tests/) | Lanceurs, comparateurs et tests de validation. |
| [`docs/`](../) | Contrats techniques, guides, résultats synthétiques et transmission. |
| `simulation-outputs/` | Résultats et archives de simulation sur la machine qui les produit. Ce dossier est ignoré par Git. |

## 5. Vérifier puis lancer la simulation

Dans le **même terminal Bash, à la racine du dépôt**, définissez `eb`. Chaque appel démarre un conteneur à usage unique dans `/project`. Le code, les modèles, les scripts, les tests et les configurations sont montés en lecture seule. Le sous-dossier de résultats est monté en écriture. Exécutez les sections suivantes depuis ce terminal, hors du Dev Container.

```bash
repo=$(git rev-parse --show-toplevel)
mkdir -p "$repo/simulation-outputs/sinergym-runs"
eb() {
  docker run --rm -i --pull never --network none --read-only --tmpfs /tmp \
    --user "$(id -u):$(id -g)" \
    -e PYTHONDONTWRITEBYTECODE=1 -e MPLCONFIGDIR=/tmp \
    -e PYTHONPATH=/project/src:/usr/local/EnergyPlus-25-1-0 \
    -v "$repo/src:/project/src:ro" -v "$repo/models:/project/models:ro" \
    -v "$repo/scripts:/project/scripts:ro" -v "$repo/tests:/project/tests:ro" \
    -v "$repo/configs:/project/configs:ro" \
    -v "$repo/simulation-outputs/sinergym-runs:/project/simulation-outputs/sinergym-runs" \
    -w /project ecobuilding-marl:dev "$@"
}

eb python /opt/ecobuilding/check_versions.py
eb python -m pip --no-cache-dir check
eb python scripts/run_sinergym_episode.py --validate-only
```

La dernière commande valide les entrées sans lancer EnergyPlus. Pour simuler la démonstration historique du 27 janvier, lancez la commande ci-dessous. Elle applique 96 fois la commande `[2, 1, 0]` après sept jours de préparation. Sa configuration conserve cinq observations historiques et une récompense nulle. Les résultats sont écrits dans un dossier d’exécution sous `simulation-outputs/sinergym-runs/office/`. [Détails du lanceur et sorties](../sinergym-usage.md)

```bash
eb python scripts/run_sinergym_episode.py --config configs/simulation/sinergym_office.json
```

## 6. Tester et reproduire les qualifications

Les trois commandes suivantes s’exécutent via `eb`, depuis la **racine du dépôt dans le terminal Ubuntu**. La première exécute la suite unitaire qualifiée (106 tests). Les deux suivantes lancent des simulations physiques. La variable d’environnement active explicitement les huit tests d’intégration Sinergym.

```bash
eb python -m unittest discover -s tests/unit -v
eb python -m unittest discover -s tests/integration -p test_energyplus.py -v
eb env ECOBUILDING_RUN_SINERGYM_INTEGRATION=1 python -m unittest discover -s tests/integration -p test_sinergym_energyplus.py -v
```

Pour reproduire la qualification physique du MDP (quatre épisodes saisonniers et un rejeu), créez un nouveau répertoire de résultats, lancez les épisodes puis analysez les traces avec le vérificateur officiel. Le rapport versionné contient les résultats de référence et les graphiques. [Qualification du MDP](../mdp-validation.md) · [Validation EnergyPlus directe](../validation.md) · [Validation de l’adaptateur](../sinergym-validation.md)

```bash
run=$(mktemp -d "$repo/simulation-outputs/sinergym-runs/mdp-XXXXXX")
out="/project/simulation-outputs/sinergym-runs/${run##*/}"
eb python scripts/validation/run_mdp_qualification.py "$out/episodes"
eb python scripts/validation/check_mdp_qualification.py "$out/episodes" --report-dir "$out/report"
```

## 7. Piloter le MDP et préparer les scénarios pour les agents

Depuis le **même terminal**, l’exemple ci-dessous enregistre les manifestes Train, Validation et Test dans un nouveau dossier. Il lance une seule décision sur le premier épisode Train, avec les 20 observations et la récompense du MDP. `scenario.reset_options()` transmet notamment le calendrier et la seed d’occupation. L’ordre des commandes est chauffage, Cooling, ventilation, chacun de niveau 0 à 2. Le bloc `finally` ferme le worker même lors d’un arrêt avant la fin de l’épisode. [Contrat du MDP](../mdp.md) · [Épisodes et manifestes](../mdp-episodes.md)

```bash
run=$(mktemp -d "$repo/simulation-outputs/sinergym-runs/prise-en-main-XXXXXX")
out="/project/simulation-outputs/sinergym-runs/${run##*/}"
eb python - "$out" <<'PY'
import sys
from pathlib import Path

from ecobuilding.episodes import EpisodePlan
from ecobuilding.sinergym_adapter import EcoBuildingEnv, STATE_NAMES

out = Path(sys.argv[1])
plan = EpisodePlan.load("configs/rl/office_mdp.json")
for split in ("train", "validation", "test"):
    plan.write_manifest(split, out / f"{split}.json")

scenario = plan.scenarios("train")[0]
env = EcoBuildingEnv(
    "models/office_1zone.epJSON",
    "models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw",
    out / "episode",
    scenario.episode,
)
try:
    observation, info = env.reset(seed=42, options=scenario.reset_options())
    print(dict(zip(STATE_NAMES, observation, strict=True)))
    observation, reward, terminated, truncated, info = env.step([2, 1, 0])
    print(observation.shape, reward, terminated, truncated)
    print(info["reward"])
finally:
    env.close()
PY
```

Les manifestes fixes de Validation et Test sont utilisables par les futurs agents avec `EpisodePlan.load_manifest()`. Conservez les mêmes couples date et seed pour comparer RBC et PPO. Le dépôt fournit les démonstrations à actions prescrites, les qualifications pseudo-aléatoires et l’interface Gymnasium pour brancher un agent. Il reste à développer la stratégie RBC, à entraîner PPO sur ce bureau et à intégrer le prototype MARL.

## 8. Résoudre les problèmes courants

| Symptôme | Vérification |
| --- | --- |
| GitHub refuse le clone ou le commit est introuvable | Vérifier l’accès au dépôt et demander la référence approuvée au groupe. |
| `docker version` affiche seulement le client ou refuse l’accès au socket | Démarrer Docker, vérifier l’intégration WSL de la bonne distribution ou suivre le README pour les permissions Docker sous Ubuntu natif. |
| Docker indique que l’image est absente | Construire le tag `ecobuilding-marl:dev` depuis la racine ou récupérer l’image qualifiée auprès du groupe. |
| EPW absent ou empreinte incorrecte | Vérifier le nom, le répertoire et le millésime, puis comparer de nouveau les empreintes. |
| Import `ecobuilding` ou `pyenergyplus` impossible | Utiliser `eb` depuis le terminal Ubuntu avec le `PYTHONPATH` du guide. |
| Écriture refusée ou résultats déjà présents | Utiliser un nouveau sous-dossier du montage de résultats et vérifier qu’il est accessible à l’utilisateur hôte. |
| Tests Sinergym ignorés | Relancer le test d’intégration avec `ECOBUILDING_RUN_SINERGYM_INTEGRATION=1` comme ci-dessus. |
| Gymnasium signale des bornes infinies ou une absence d’`EnvSpec` | Trois avertissements de ce type sont documentés dans la qualification logicielle. Examiner séparément tout autre avertissement. |
| Un épisode échoue | Consulter les journaux EnergyPlus (`eplusout.err`) et, pour le lanceur officiel, le `summary.json` lorsqu’il est disponible. Comparer la météo, la configuration et les versions aux valeurs qualifiées. |

## 9. Vérifications restantes sur un second poste

- Confirmer avec le compte d’un coéquipier l’accès au dépôt GitHub et au commit technique de référence depuis un clone propre.
- Vérifier le build `linux/amd64` et les versions obtenues, ainsi que les permissions Docker sous Ubuntu natif et l’intégration Docker Desktop sous WSL2.
- Vérifier l’ouverture du Dev Container dans VS Code et la cellule Jupyter de contrôle du README.
- Confirmer l’accès à l’EPW, son empreinte et le succès de `--validate-only` sur le poste destinataire.

[Checklist d’installation du README](../../README.md#validation-sur-un-second-ordinateur)
