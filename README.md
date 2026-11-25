
# EcoBuilding-MARL

Intelligent Building Energy Management using
Multi-Agent Reinforcement Learning.

## Project Overview

This project aims to optimize building energy consumption
while maintaining indoor thermal comfort.

## Passation des lots 1 et 2

Le modèle EnergyPlus, l’intégration Sinergym et le MDP sont opérationnels et qualifiés en simulation. Le développement RBC, l’entraînement PPO sur le bureau officiel et le prototype MARL restent à réaliser. La branche de transmission est `feature/lot1-lot2-building-environment`. La référence technique qualifiée est `cec22b6a076da718d05f7b2bc1559c3feae9bcd0`. Lors de la vérification 2.4, le commit documentaire publié était `fe9dbc894bcf7e0cfff85c3303f480a200fd9e06`.

Commencez par le [guide de prise en main](docs/handover/quickstart.md), puis consultez le [rapport de transmission](docs/handover/handover.md) et l’[inventaire des ressources](docs/handover/inventory.md). La [capitalisation technique](docs/handover/technical-knowledge.md) fait partie du référentiel documentaire versionné. Le [rapport de transmission](docs/handover/handover.md#6-décisions-techniques-à-préserver) donne aussi les contrats essentiels à préserver depuis un clone.

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

## requirement

- Intel PC or AMD 64-bit (`x86_64`), under Windows 11 or Ubuntu supported by Docker Engine. Ubuntu 24.04 LTS is suitable for native Linux use. The target image is `linux/amd64`.
- On Windows, enable hardware virtualization in the BIOS/UEFI. Docker Desktop requires at least 8 GB of RAM. Allow several GB of free space for the image and build cache on both systems. [Docker Desktop Prerequisites](https://docs.docker.com/desktop/setup/install/windows-install/)
- Provide access to the GitHub repository and an internet connection for the first build. Docker downloads the base image, Ubuntu packages, EnergyPlus and Python dependencies.

The image Ubuntu 24.04 installs Python, EnergyPlus, Sinergym, Gymnasium, Stable-Baselines3, PyTorch CPU and the Jupyter kernel. No separate installation of these components or dedicated graphics card is required on the PC.

<a name="windows-11-avec-wsl2"></a>

## Windows 11 with WSL2

### 1. Install Ubuntu in WSL2

In **PowerShell administrateur** :

```powershell
wsl --install -d Ubuntu
```

Restart if Windows requests it. Open **Ubuntu** from the Start menu and create your Linux account. In **PowerShell** :

```powershell
wsl --update
wsl --version
wsl -l -v
```

The `Ubuntu` line must display `2` in the `VERSION`column. If it displays `1`, run `wsl --set-version Ubuntu 2`, then rerun `wsl -l -v`. [Microsoft WSL Guide](https://learn.microsoft.com/windows/wsl/install)

### 2. Installer Docker Desktop

In **PowerShell**, with WinGet available:

```powershell
winget install --id Docker.DockerDesktop --exact
```

You can also use the official installer. Launch Docker Desktop, select the WSL2 engine in **Settings → General** if the option is displayed, then activate **Ubuntu** in **Settings → Resources → WSL Integration** and apply the changes. Use Linux container mode. Docker Desktop provides the `docker` command to Ubuntu via this integration. [Docker Desktop Installation](https://docs.docker.com/desktop/setup/install/windows-install/), [WSL2 Integration](https://docs.docker.com/desktop/features/wsl/)

In the **Ubuntu WSL* terminal** :

```bash
docker version
```

The command must display the **Client** and **Server** sections, with a Linux server.

### 3. Install Git

In the **Ubuntu WSL* terminal** :

```bash
sudo apt update
sudo apt install -y git
git --version
```

### 4. Install VS Code

In **PowerShell** :

```powershell
winget install --id Microsoft.VisualStudioCode --exact
```

Open a new **PowerShell** window to retrieve the `code`command, then install the extensions:

```powershell
code --install-extension ms-vscode-remote.remote-wsl
code --install-extension ms-vscode-remote.remote-containers
code --install-extension ms-python.python
code --install-extension ms-toolsai.jupyter
```

The repository configuration also installs Python and Jupyter into the container. Continue with the [common steps](#clone-build-and-open-the-project) from **Ubuntu WSL**.

<a name="linux-ubuntu-natif"></a>

## Linux Ubuntu native

### 1. Install Docker Engine and Compose

In the **native Ubuntu terminal*, add the official APT repository of Docker on an installation without competing Docker packages. If Docker is already installed, check its origin and any conflicts before changing your installation. [Docker Engine Guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

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

You must see a Docker client and server, as well as the version of the Compose plugin.

### 2. Allow access to Docker for VS Code

On a **personal workstation**, if the workstation’s policy allows it, add only your trusted account to the `docker` group so that Dev Containers can join the engine:

```bash
sudo usermod -aG docker "$USER"
```

Close your Ubuntu session completely and log in again before launching VS Code. Then check:

```bash
id -nG
docker version
```

The group `docker` grants privileges equivalent to `root`. On a shared or administered workstation, ask the administrator for approved access, such as a rootless engine. The Dev Containers path with a rootless engine remains to be verified for this project. Keep the Docker socket permissions in place and launch VS Code with your user account. [Docker permissions](https://docs.docker.com/engine/install/linux-postinstall/), [Docker rootless](https://docs.docker.com/engine/security/rootless/)

### 3. Install Git

In the **native Ubuntu terminal** :

```bash
sudo apt install -y git
git --version
```

### 4. Install VS Code

In the **native Ubuntu terminal**, with Snap available:

```bash
sudo snap install --classic code
code --install-extension ms-vscode-remote.remote-containers
code --install-extension ms-python.python
code --install-extension ms-toolsai.jupyter
```

The official `.deb` package is also available. Continue with the common steps from this same terminal. [Installing VS Code on Linux](https://code.visualstudio.com/docs/setup/linux)

<a name="cloner-construire-et-ouvrir-le-projet"></a>

## Clone, build, and open the project

Run the following commands in the **Ubuntu WSL* terminal* on Windows or in the **native Ubuntu terminal** on Linux.

### 5. Clone in `~/projects`

```bash
mkdir -p ~/projects
cd ~/projects
git clone --branch feature/lot1-lot2-building-environment https://github.com/Blangi-Aladdin/EcoBuilding-MARL.git
cd EcoBuilding-MARL
git branch --show-current
ls -la Dockerfile .devcontainer/devcontainer.json requirements.lock requirements-build.lock
```

Before the final merge, the command above explicitly checks out the lots 1 and 2 delivery branch. Expect `feature/lot1-lot2-building-environment` and the four files listed above. Once these lots are integrated into `main`, you can clone with `git clone --branch main https://github.com/Blangi-Aladdin/EcoBuilding-MARL.git` and expect `main`. If access is restricted, use an authorized GitHub account. If the Docker files are missing, check the branch before starting the build.

### 6. Build the image

```bash
docker build --platform linux/amd64 -t ecobuilding-marl:dev .
```

The build must finish with the local image `ecobuilding-marl:dev`.

### 7. Check versions

```bash
docker image inspect ecobuilding-marl:dev --format '{{.Os}}/{{.Architecture}}'
docker run --rm ecobuilding-marl:dev python /opt/ecobuilding/check_versions.py
docker run --rm ecobuilding-marl:dev python -m pip check
```

Expect to see `linux/amd64`, Python 3.12 (3.12.3 during testing), EnergyPlus 25.1.0 (build `1c11a3d85f`), Sinergym 3.12.2, Gymnasium 1.2.3, Stable-Baselines3 2.7.1, PyTorch `2.9.1+cpu`, ipykernel 6.30.1, and `No broken requirements found. ` The script loads the EnergyPlus API and verifies the NumPy–PyTorch conversion without running any simulation or training.

To get an interactive shell with the mounted repository:

```bash
docker run --rm -it --mount "type=bind,source=$PWD,target=/workspaces/EcoBuilding-MARL" ecobuilding-marl:dev
```

### 8. Open the Dev Container

From the cloned folder, run `code . `. On Windows, the window must first indicate **WSL: Ubuntu**. In the VS Code command palette, launch **Dev Containers: Reopen in Container**. Wait for the window to indicate that it is connected to the container. VS Code builds its container from the same Dockerfile.

### 9. Check Python and Jupyter

From the palette, open **Python: Select Interpreter** and select `/opt/venv/bin/python` In the container’s built-in terminal, verify:

```bash
command -v python
python --version
python -m jupyter kernelspec list
```

The expected result is `/opt/venv/bin/python`, Python 3.12.x and a `python3` kernel in `/opt/venv/share/jupyter/kernels`. In a notebook, choose **Select Kernel → Python Environments**, then the container interpreter. In a cell, execute `import sys; print(sys.executable)` and verify that the output is `/opt/venv/bin/python`.

<a name="validation-sur-un-second-ordinateur"></a>

## Validation on a second computer

The Docker image, EnergyPlus and Sinergym qualifications, and the MDP have been verified locally. Historical PPO checks are separate from training on the official Sinergym office, which remains to be done. On a second workstation, confirm GitHub access with a group member’s account, access to the qualified technical commit, a build from a clean clone, Docker permissions on native Ubuntu, reopening in VS Code, and execution of the Jupyter cell. Validate each setup on its respective system. [Quickstart checklist](docs/handover/quickstart.md#9-vérifications-restantes-sur-un-second-poste)

## Local outputs

Run the [quickstart simulation commands](docs/handover/quickstart.md#5-vérifier-puis-lancer-la-simulation) from the repository root. They write to `simulation-outputs/`, which Git ignores, along with the directories generated by the historical `Eplus-demo-v1` demo. Keep local credentials out of the shared repository. A clone contains the versioned protocols and summaries. Obtain the EPW separately from the supplier and request the detailed qualification archives from the group. [Evidence inventory](docs/handover/inventory.md#5-inventaire-des-preuves-de-validation)

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
