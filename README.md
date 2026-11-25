
# EcoBuilding-MARL

Intelligent Building Energy Management using
Multi-Agent Reinforcement Learning.

## Project Overview

This project aims to optimize building energy consumption
while maintaining indoor thermal comfort.

## Technologies

- Python
- EnergyPlus
- Sinergym
- Stable-Baselines3 (PPO)
- Docker
- WSL2
- Jupyter Notebook

## Objectives

- Simulate building energy consumption.
- Train reinforcement learning agents.
- Optimize HVAC control strategies.
- Compare RL performance with rule-based control (RBC).
- Extend the system toward multi-agent coordination.

## Prérequis

- PC Intel ou AMD 64 bits (`x86_64`), sous Windows 11 ou Ubuntu pris en charge par Docker Engine. Ubuntu 24.04 LTS convient au parcours Linux natif. L’image cible est `linux/amd64`.
- Sous Windows, activez la virtualisation matérielle dans le BIOS/UEFI. Docker Desktop demande au moins 8 Go de RAM. Prévoyez plusieurs Go d’espace libre pour l’image et le cache de build sur les deux systèmes. [Prérequis Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
- Prévoyez un accès au dépôt GitHub et une connexion Internet pour le premier build. Docker télécharge l’image de base, les paquets Ubuntu, EnergyPlus et les dépendances Python.

L’image Ubuntu 24.04 installe Python, EnergyPlus, Sinergym, Gymnasium, Stable-Baselines3, PyTorch CPU et le noyau Jupyter. Aucune installation séparée de ces composants ni carte graphique dédiée n’est requise sur le PC.

## Windows 11 avec WSL2

### 1. Installer Ubuntu dans WSL2

Dans **PowerShell administrateur** :

```powershell
wsl --install -d Ubuntu
```

Redémarrez si Windows le demande. Ouvrez **Ubuntu** depuis le menu Démarrer et créez votre compte Linux. Dans **PowerShell** :

```powershell
wsl --update
wsl --version
wsl -l -v
```

La ligne `Ubuntu` doit afficher `2` dans la colonne `VERSION`. Si elle affiche `1`, exécutez `wsl --set-version Ubuntu 2`, puis relancez `wsl -l -v`. [Guide Microsoft WSL](https://learn.microsoft.com/windows/wsl/install)

### 2. Installer Docker Desktop

Dans **PowerShell**, avec WinGet disponible :

```powershell
winget install --id Docker.DockerDesktop --exact
```

Vous pouvez aussi utiliser l’installateur officiel. Lancez Docker Desktop, sélectionnez le moteur WSL2 dans **Settings → General** si l’option est affichée, puis activez **Ubuntu** dans **Settings → Resources → WSL Integration** et appliquez les changements. Utilisez le mode conteneurs Linux. Docker Desktop fournit la commande `docker` à Ubuntu via cette intégration. [Installation Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/), [Intégration WSL2](https://docs.docker.com/desktop/features/wsl/)

Dans le **terminal Ubuntu WSL** :

```bash
docker version
```

La commande doit afficher les sections **Client** et **Server**, avec un serveur Linux.

### 3. Installer Git

Dans le **terminal Ubuntu WSL** :

```bash
sudo apt update
sudo apt install -y git
git --version
```

### 4. Installer VS Code

Dans **PowerShell** :

```powershell
winget install --id Microsoft.VisualStudioCode --exact
```

Ouvrez une nouvelle fenêtre **PowerShell** pour récupérer la commande `code`, puis installez les extensions :

```powershell
code --install-extension ms-vscode-remote.remote-wsl
code --install-extension ms-vscode-remote.remote-containers
code --install-extension ms-python.python
code --install-extension ms-toolsai.jupyter
```

La configuration du dépôt installe également Python et Jupyter dans le conteneur. Poursuivez avec les [étapes communes](#cloner-construire-et-ouvrir-le-projet) depuis **Ubuntu WSL**.

## Linux Ubuntu natif

### 1. Installer Docker Engine et Compose

Dans le **terminal Ubuntu natif**, ajoutez le dépôt APT officiel de Docker sur une installation sans paquets Docker concurrents. Si Docker est déjà installé, vérifiez sa provenance et les conflits éventuels avant de changer d’installation. [Guide Docker Engine pour Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
docker compose version
```

Vous devez voir un client et un serveur Docker, ainsi que la version du plugin Compose.

### 2. Autoriser l’accès à Docker pour VS Code

Sur un **poste personnel**, si la politique du poste le permet, ajoutez uniquement votre compte de confiance au groupe `docker` pour que Dev Containers puisse joindre le moteur :

```bash
sudo usermod -aG docker "$USER"
```

Fermez entièrement votre session Ubuntu et reconnectez-vous avant de lancer VS Code. Puis vérifiez :

```bash
id -nG
docker version
```

Le groupe `docker` confère des privilèges équivalents à `root`. Sur un poste partagé ou administré, demandez à l’administrateur un accès approuvé, par exemple un moteur rootless. Le parcours Dev Containers avec un moteur rootless reste à vérifier pour ce projet. Gardez les permissions du socket Docker en place et lancez VS Code avec votre compte utilisateur. [Permissions Docker](https://docs.docker.com/engine/install/linux-postinstall/), [Docker rootless](https://docs.docker.com/engine/security/rootless/)

### 3. Installer Git

Dans le **terminal Ubuntu natif** :

```bash
sudo apt install -y git
git --version
```

### 4. Installer VS Code

Dans le **terminal Ubuntu natif**, avec Snap disponible :

```bash
sudo snap install --classic code
code --install-extension ms-vscode-remote.remote-containers
code --install-extension ms-python.python
code --install-extension ms-toolsai.jupyter
```

Le paquet officiel `.deb` est également disponible. Poursuivez avec les étapes communes depuis ce même terminal. [Installation de VS Code sous Linux](https://code.visualstudio.com/docs/setup/linux)

## Cloner, construire et ouvrir le projet

Exécutez les commandes suivantes dans le **terminal Ubuntu WSL** sous Windows ou dans le **terminal Ubuntu natif** sous Linux.

### 5. Cloner dans `~/projects`

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/Blangi-Aladdin/EcoBuilding-MARL.git
cd EcoBuilding-MARL
git branch --show-current
ls -la Dockerfile .devcontainer/devcontainer.json requirements.lock requirements-build.lock
```

Attendez-vous à voir la branche `main` et les quatre fichiers listés. Si le dépôt est privé, utilisez un compte GitHub autorisé. Si les fichiers Docker sont absents, vérifiez avec le groupe que la branche contenant la configuration a bien été partagée avant de lancer le build.

### 6. Construire l’image

```bash
docker build --platform linux/amd64 -t ecobuilding-marl:dev .
```

Le build doit terminer avec l’image locale `ecobuilding-marl:dev`.

### 7. Vérifier les versions

```bash
docker image inspect ecobuilding-marl:dev --format '{{.Os}}/{{.Architecture}}'
docker run --rm ecobuilding-marl:dev python /opt/ecobuilding/check_versions.py
docker run --rm ecobuilding-marl:dev python -m pip check
```

Attendez-vous à voir `linux/amd64`, Python 3.12 (3.12.3 lors du test), EnergyPlus 25.1.0 (build `1c11a3d85f`), Sinergym 3.12.2, Gymnasium 1.2.3, Stable-Baselines3 2.7.1, PyTorch `2.9.1+cpu`, ipykernel 6.30.1 et `No broken requirements found.` Le script charge l’API EnergyPlus et vérifie la conversion NumPy–PyTorch sans lancer de simulation ni d’entraînement.

Pour obtenir un shell interactif avec le dépôt monté :

```bash
docker run --rm -it --mount "type=bind,source=$PWD,target=/workspaces/EcoBuilding-MARL" ecobuilding-marl:dev
```

### 8. Ouvrir le Dev Container

Depuis le dossier cloné, exécutez `code .`. Sous Windows, la fenêtre doit d’abord indiquer **WSL: Ubuntu**. Dans la palette de commandes de VS Code, lancez **Dev Containers: Reopen in Container**. Attendez que la fenêtre indique qu’elle est connectée au conteneur. VS Code construit son conteneur depuis le même Dockerfile.

### 9. Vérifier Python et Jupyter

Dans la palette, ouvrez **Python: Select Interpreter** et sélectionnez `/opt/venv/bin/python`. Dans le terminal intégré du conteneur, vérifiez :

```bash
command -v python
python --version
python -m jupyter kernelspec list
```

Le résultat attendu est `/opt/venv/bin/python`, Python 3.12.x et un noyau `python3` dans `/opt/venv/share/jupyter/kernels`. Dans un notebook, choisissez **Select Kernel → Python Environments**, puis l’interpréteur du conteneur. Dans une cellule, exécutez `import sys; print(sys.executable)` et vérifiez que le résultat est `/opt/venv/bin/python`.

## Validation sur un second ordinateur

L’image et les essais historiques EnergyPlus, Sinergym et PPO ont été validés localement. L’entraînement PPO sur le bureau Sinergym officiel reste à réaliser. Sur un autre poste, il reste à confirmer l’accès GitHub avec le compte d’un membre du groupe, le build depuis un clone propre, les permissions Docker sous Ubuntu natif, la réouverture dans VS Code et l’exécution de la cellule Jupyter. Validez les deux parcours sur leurs systèmes respectifs. Vérifiez aussi que le commit technique est accessible depuis le clone du coéquipier. [Guide de prise en main et vérifications restantes](docs/handover/quickstart.md#9-vérifications-restantes-sur-un-second-poste)

## Sorties locales

Lancez les simulations depuis `simulation-outputs/` à la racine du projet si vous souhaitez conserver les résultats sur le PC. Ce dossier et les répertoires générés par la démo `Eplus-demo-v1` sont ignorés par Git. Gardez les identifiants locaux hors du dépôt partagé.

### Dependency updates

The image pins the Ubuntu amd64 manifest, the Ubuntu package snapshot and the
SHA-256 of the EnergyPlus installer. The EnergyPlus layout follows the
[Sinergym 3.12.2 Dockerfile](https://github.com/ugr-sail/sinergym/blob/v3.12.2/Dockerfile).
The Python lock includes hashes for direct and transitive dependencies.
To regenerate it after changing `requirements.in`, use `uv` from Ubuntu, under WSL2 or on native Linux. A normal build uses the committed lock files directly.

```bash
uv pip compile requirements.in --python-version 3.12 \
  --python-platform x86_64-manylinux_2_39 --generate-hashes \
  --output-file requirements.lock
uv pip compile requirements-build.in --python-version 3.12 \
  --generate-hashes --only-binary :all: --output-file requirements-build.lock
```

The separate build lock pins setuptools and wheel for `tinynumpy`, which
is distributed as a source archive. The image uses wheels for the other
Python dependencies.

## Validation du bureau monozone EnergyPlus

Le code sous `src/ecobuilding/` fournit les commandes HVAC, l’occupation dynamique,
les observations et le coordinateur des simulations. La validation s’exécute
avec le modèle principal, l’EPW local et l’image `ecobuilding-marl:dev`.

- [Architecture et conventions de mesure](docs/architecture.md)
- [Reproduire les tests EnergyPlus](docs/validation.md)

## Environnement Sinergym officiel

Le package `ecobuilding.sinergym_adapter` expose le bureau monozone sous
l’interface Gymnasium. Le runner EnergyPlus direct reste disponible pour
régénérer les références. Le modèle et l’EPW Belfort–Fontaine sont communs
aux deux parcours. [Modèle et météo](models/README.md)

- [Utilisation, configuration JSON et commandes Docker](docs/sinergym-usage.md)
- [Architecture, contrat temporel, énergie et limites](docs/sinergym-architecture.md)
- [Tests logiciels, intégration physique et qualification](docs/sinergym-validation.md)

Le MDP est qualifié avec **106 tests unitaires** et cinq épisodes physiques,
dont un rejeu hivernal exact. Les prochaines étapes définiront les stratégies
RBC et PPO et leurs comparaisons sur les mêmes manifestes.

- [Contrat MDP, espace d’observation et récompense](docs/mdp.md)
- [Épisodes Train, Validation et Test](docs/mdp-episodes.md)
- [Résultats et reproduction de la qualification MDP](docs/mdp-validation.md)
