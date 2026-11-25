# Inventaire des livrables de transmission

## 1. Identification du périmètre

- **Projet** — EcoBuilding-MARL.
- **Lots** — lot 1, modèle physique EnergyPlus et pilotage direct. Lot 2, intégration Sinergym et MDP pour la commande HVAC.
- **Branche de transmission** — [`feature/lot1-lot2-building-environment`](https://github.com/Blangi-Aladdin/EcoBuilding-MARL/tree/feature/lot1-lot2-building-environment).
- **Commit de référence** — `cec22b6a076da718d05f7b2bc1559c3feae9bcd0`.
- **Objectif** — permettre aux coéquipiers de retrouver les livrables, de distinguer les preuves accessibles dans Git des archives locales et de préparer les travaux RBC et PPO.

Les statuts décrivent la disponibilité de chaque livrable pour un coéquipier qui dispose du commit de référence. **Complet** signifie que le livrable remplit son rôle dans ce périmètre. **Partiel** signifie qu’une partie des preuves ou des contenus reste à transmettre. **Manquant** signifie que le livrable dédié est à produire. Les chemins des tableaux sont relatifs à la racine du dépôt. Dans un chemin entre accolades, chaque nom désigne un fichier distinct.

Les liens marqués **local** ciblent le workspace audité. Ils fonctionnent après récupération des archives au même emplacement relatif. Les lots 3 à 6 pourront reprendre les cinq catégories et la même échelle de statut dans de nouvelles sections. La synthèse scientifique détaillée relève du futur `technical-knowledge.md`.

## 2. Inventaire du lot 1 — EnergyPlus

| Livrable | Chemins exacts | Contenu et utilité | Statut |
|---|---|---|---|
| Code source et configurations | [`models/office_1zone.epJSON`](../../models/office_1zone.epJSON), [`configs/validation/lot1.json`](../../configs/validation/lot1.json), `src/ecobuilding/{actions,_cooling_base,cooling,observations,occupancy,occupancy_profiles,simulation}.py` | Modèle monozone, pilotes HVAC, occupation, mesures et runner direct. Sert à simuler le bureau et à régénérer des références physiques. | **Complet** |
| Documentation technique | [`models/README.md`](../../models/README.md), [`docs/architecture.md`](../architecture.md) | Hypothèses de bâtiment, équipements, interfaces de commande et conventions de lecture et d’agrégation. Sert à interpréter les sorties du moteur. | **Complet** |
| Guide d’utilisation | [`README.md`](../../README.md), [`docs/validation.md`](../validation.md) | Installation, récupération et empreinte de l’EPW, montage des entrées et commande de rejeu isolé. Sert à lancer le runner direct depuis un clone préparé. | **Complet** |
| Tests et résultats | `tests/unit/test_{actions,cooling,observations,occupancy,simulation}.py`, [`tests/integration/test_energyplus.py`](../../tests/integration/test_energyplus.py), `scripts/validation/{run,checks,compare_reference}.py`. **Local** [`simulation-outputs/lot1-global-validation/`](../../simulation-outputs/lot1-global-validation/) | Tests et outils versionnés pour contrôler les 19 scénarios du rejeu direct. Le rapport final 36.7, les journaux natifs et les rapprochements API/CSV sont conservés localement. | **Partiel** |
| Rapport de transmission | Rapport dédié à créer. Source **locale** [`simulation-outputs/lot1-global-validation/README.md`](../../simulation-outputs/lot1-global-validation/README.md). | La qualification fournit la matière du rapport. La passation devra relier le périmètre, le démarrage, les résultats et les réserves. | **Manquant** |

## 3. Inventaire du lot 2 — Sinergym et MDP

| Livrable | Chemins exacts | Contenu et utilité | Statut |
|---|---|---|---|
| Code source et configurations | `src/ecobuilding/sinergym_adapter/{__init__,environment,model,reward,simulator,state,transport}.py`, [`src/ecobuilding/episodes.py`](../../src/ecobuilding/episodes.py), [`configs/rl/office_mdp.json`](../../configs/rl/office_mdp.json), [`configs/simulation/sinergym_office.json`](../../configs/simulation/sinergym_office.json), [`configs/validation/lot2_sinergym.json`](../../configs/validation/lot2_sinergym.json) | Façade Gymnasium, état, actions, récompense, calendrier et manifestes. Sert de point d’entrée aux futurs agents et réutilise les gestionnaires du lot 1. | **Complet** |
| Documentation technique | [`docs/sinergym-architecture.md`](../sinergym-architecture.md), [`docs/mdp.md`](../mdp.md), [`docs/mdp-episodes.md`](../mdp-episodes.md) | Cycle de vie du worker, contrat MDP, temporalité, récompense, seeds et séparation météo. Sert de référence au développement et à l’évaluation. | **Complet** |
| Guide d’utilisation | [`docs/sinergym-usage.md`](../sinergym-usage.md), [`docs/mdp-episodes.md`](../mdp-episodes.md), [`scripts/run_sinergym_episode.py`](../../scripts/run_sinergym_episode.py) | Montage Docker, initialisation, `reset`, `step`, `close`, décomposition de la récompense et génération de manifestes. Sert à brancher un contrôleur ou à rejouer une configuration. | **Complet** |
| Tests et résultats | [`tests/integration/test_sinergym_energyplus.py`](../../tests/integration/test_sinergym_energyplus.py), `tests/unit/sinergym_adapter/{__init__,doubles,test_mdp,test_qualification,test_reward,test_state,test_transport}.py`, `tests/unit/test_{episodes,sinergym_comparator}.py`, `scripts/validation/{_sinergym_compare,_sinergym_replay,run_sinergym_qualification,run_mdp_qualification,check_mdp_qualification}.py`, [`docs/sinergym-validation.md`](../sinergym-validation.md), [`docs/mdp-validation.md`](../mdp-validation.md), `docs/assets/mdp/{energie-recompense,temperature-occupation}.png`. Archives détaillées **locales** en section 5. | Les tests, les critères, les commandes et la synthèse MDP sont versionnés. Les preuves détaillées d’équivalence Sinergym et les sorties natives sont locales. | **Partiel** |
| Rapport de transmission | Rapport dédié à créer. Points d’entrée existants [`README.md`](../../README.md) et [`docs/mdp-validation.md`](../mdp-validation.md). | Relier l’environnement validé, les preuves Sinergym et MDP et les travaux RBC/PPO qui restent à mener. | **Manquant** |

## 4. Ressources communes

| Ressource | Chemins et disponibilité | Usage |
|---|---|---|
| Environnement de développement | **Git** [`Dockerfile`](../../Dockerfile), [`.devcontainer/devcontainer.json`](../../.devcontainer/devcontainer.json), [`docker/check_versions.py`](../../docker/check_versions.py), [`README.md`](../../README.md) | Image de référence `ecobuilding-marl:dev` sur `linux/amd64`, via Linux ou Ubuntu WSL. L’image construite reste hors Git. Le premier build demande un accès réseau aux sources de dépendances. |
| Dépendances | **Git** [`requirements.in`](../../requirements.in), [`requirements.lock`](../../requirements.lock), [`requirements-build.in`](../../requirements-build.in), [`requirements-build.lock`](../../requirements-build.lock) | Pile qualifiée avec Python 3.12.3, EnergyPlus 25.1.0-1c11a3d85f, Sinergym 3.12.2, Gymnasium 1.2.3, SB3 2.7.1, NumPy 2.5.5 et PyTorch CPU 2.9.1+cpu. |
| Entrées et validation communes | **Git** [`models/office_1zone.epJSON`](../../models/office_1zone.epJSON), [`configs/validation/lot1.json`](../../configs/validation/lot1.json), [`scripts/validation/checks.py`](../../scripts/validation/checks.py) | Le modèle et les gestionnaires métier servent aux deux lots. Le lot 2 réutilise la configuration du lot 1 pour régénérer les références directes. |
| Météo | **Local** [`models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw`](../../models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw). Récupération et empreintes dans [`docs/validation.md`](../validation.md). | Extraire l’archive du fournisseur à l’emplacement attendu. SHA-256 `c3abc4cfd50efc65d6a7bdb7e35c3b7716489f803fc2135747833d6192e6725a`. Garder le fichier hors Git en attendant la confirmation des droits de redistribution. |

## 5. Inventaire des preuves de validation

| Périmètre | Ressources versionnées | Archives uniquement locales |
|---|---|---|
| Lot 1, validation directe 36.7 | Cas du [lot 1](../../configs/validation/lot1.json), [test d’intégration](../../tests/integration/test_energyplus.py) et [procédure de rejeu](../validation.md). | [Rapport](../../simulation-outputs/lot1-global-validation/README.md), [inventaire des exécutions](../../simulation-outputs/lot1-global-validation/runs.csv), [comparaison API/CSV](../../simulation-outputs/lot1-global-validation/validation-api-csv.csv), [bilan électrique](../../simulation-outputs/lot1-global-validation/bilan-energetique.csv) et [traces du rejeu](../../simulation-outputs/lot1-global-validation/replay/). Le rejeu final compte 19 scénarios et 3 648 pas de zone. |
| Lot 2, qualification Sinergym 37.2.7.5 | [Cas et tolérances](../../configs/validation/lot2_sinergym.json), [orchestrateur](../../scripts/validation/run_sinergym_qualification.py), [comparateur corrigé](../../scripts/validation/_sinergym_compare.py), [tests de régression](../../tests/unit/test_sinergym_comparator.py). | [Rapport final](../../simulation-outputs/lot2-sinergym-prototype/results/37.2.7.5-final-qualification/qualification-simplifiee/README.md), [résultats d’équivalence](../../simulation-outputs/lot2-sinergym-prototype/results/37.2.7.5-final-qualification/qualification-simplifiee/equivalence-verifiee.json), [inventaire moteur](../../simulation-outputs/lot2-sinergym-prototype/results/37.2.7.5-final-qualification/qualification-simplifiee/inventaire-executions.csv) et [contrôles du comparateur](../../simulation-outputs/lot2-sinergym-prototype/results/37.2.7.5-final-qualification/phase-a-correction/tests-negatifs-avant-apres.csv). La campagne finale consigne 59 exécutions et 14 cas d’équivalence exacte. |
| Lot 2, qualification MDP 38.8.4–38.8.5 | [Rapport et tableaux MDP](../mdp-validation.md), [énergie et pénalités](../assets/mdp/energie-recompense.png), [température et occupation](../assets/mdp/temperature-occupation.png), [lanceur physique](../../scripts/validation/run_mdp_qualification.py) et [vérificateur indépendant](../../scripts/validation/check_mdp_qualification.py). La suite globale compte 106 tests réussis. | [Rapport de campagne](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/README.md), [bilan CSV](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/synthese.csv), [écarts détaillés](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/resultats.json), [journal](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/execution.txt) et [manifestes, actions et traces des épisodes](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/episodes/). Les quatre épisodes Train et le rejeu hivernal totalisent 3 360 transitions. |

Les résultats MDP caractérisent une séquence pseudo-aléatoire de qualification. Les performances RBC et PPO restent à établir.

## 6. Éléments restant à transmettre

| Priorité | Constat de 38.T.1 | Action restante |
|---|---|---|
| **P1 — Accès au commit** | Lors de l’audit 38.T.1, la branche `feature/lot1-building-model` était locale. Le commit de référence est désormais accessible sur la branche de transmission publiée. | Confirmer l’accès depuis un nouveau clone sur le poste d’un coéquipier. |
| **P1 — Entrées et environnement** | Un clone ne contient ni l’EPW ni l’image Docker construite. | Confirmer que les destinataires peuvent obtenir l’EPW, vérifier son empreinte et construire ou obtenir l’image. |
| **P2 — Rapports et preuves** | Les rapports de transmission des deux lots restent à produire. Les preuves finales 36.7 et 37.2.7.5 sont locales. | Préparer la passation et donner accès aux synthèses de qualification. Garder les sorties brutes volumineuses en archive séparée. |
| **P2 — Comparaison des agents** | Le MDP et les scénarios sont disponibles. Le protocole opérationnel de comparaison RBC/PPO reste à convenir. | Fixer les manifestes communs, les seeds propres aux agents, les métriques et la règle de sélection sur Validation avant l’évaluation sur Test. |
| **P3 — Cohérence des guides** | L’équivalence du package officiel est consignée dans la [documentation Sinergym](../sinergym-validation.md#qualification-finale-du-package-officiel). Le [guide de prise en main](quickstart.md#6-tester-et-reproduire-les-qualifications) distingue le test EnergyPlus direct des huit tests physiques Sinergym, qui exigent une activation explicite. | Le [guide de validation du lot 1](../validation.md) utilise encore la découverte globale pour les tests d’intégration. |

## 7. Index des ressources

| Besoin | Ressource de départ | Disponibilité |
|---|---|---|
| Installer l’environnement ou vérifier les versions | [Installation](../../README.md), [contrôle des versions](../../docker/check_versions.py) | Git |
| Récupérer la météo et vérifier les empreintes | [Guide EnergyPlus](../validation.md) | Guide dans Git, EPW local |
| Comprendre le bureau, les équipements ou les mesures | [Modèle](../../models/README.md), [architecture EnergyPlus](../architecture.md) | Git |
| Lancer EnergyPlus direct | [Commande et contrôles](../validation.md), [runner de validation](../../scripts/validation/run.py) | Git, avec EPW local |
| Comprendre la façade et ses callbacks | [Architecture Sinergym](../sinergym-architecture.md), [façade](../../src/ecobuilding/sinergym_adapter/environment.py) | Git |
| Brancher un agent et interpréter la récompense | [Contrat MDP](../mdp.md), [exemple d’utilisation](../sinergym-usage.md) | Git |
| Partager des épisodes entre RBC et PPO | [Calendrier et manifestes](../mdp-episodes.md), [plan d’épisodes](../../src/ecobuilding/episodes.py) | Git |
| Choisir la suite de tests ou reproduire la qualification MDP | [Validation Sinergym](../sinergym-validation.md), [validation MDP](../mdp-validation.md) | Git |
| Vérifier les résultats détaillés de qualification | [EnergyPlus direct](../../simulation-outputs/lot1-global-validation/README.md), [équivalence Sinergym](../../simulation-outputs/lot2-sinergym-prototype/results/37.2.7.5-final-qualification/qualification-simplifiee/README.md), [qualification MDP](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/README.md) | Local |
