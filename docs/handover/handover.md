# Rapport de transmission — Lots 1 et 2

**Projet** — EcoBuilding-MARL\
**Référence technique** — branche `feature/lot1-building-model`, commit `cec22b6a076da718d05f7b2bc1559c3feae9bcd0`.

Ce commit contient le modèle EnergyPlus, l’adaptateur Sinergym et le MDP qualifié. Les résultats chiffrés ci-dessous décrivent leur qualification logicielle et physique en simulation. Les performances des futures stratégies restent à établir. Les liens marqués **archive locale** pointent vers des preuves hors Git.

## 1. Contexte et objectifs

Le projet étudie le compromis entre consommation électrique, confort thermique et qualité de l’air dans un bureau monozone. Il fournit un banc d’essai où les commandes de chauffage, de refroidissement et de ventilation peuvent être comparées sur des conditions météorologiques et des profils d’occupation reproductibles.

Les deux premiers lots établissent la physique du bureau et le contrat de décision. Les lots suivants développeront et compareront les stratégies de contrôle. [Inventaire des livrables](inventory.md) · [Connaissances scientifiques et techniques](technical-knowledge.md)

## 2. Architecture générale

```text
Futur agent → EcoBuildingEnv → Transport → Worker Sinergym → EnergyPlus
                   ↑                                              │
                   └──── observations, récompense et diagnostics ──┘

SimulationRunner direct ──→ mêmes gestionnaires métier ──→ EnergyPlus
```

La façade Gymnasium accepte une action à chaque frontière de décision. Le worker Sinergym applique les commandes et l’occupation aux callbacks prévus. EnergyPlus résout l’intervalle et ses sous-pas HVAC. Les gestionnaires métier collectent les mesures, la façade calcule l’état et la récompense, puis renvoie le résultat associé à la décision. Le runner direct utilise les mêmes gestionnaires et fournit une référence indépendante de l’adaptateur. [Architecture EnergyPlus](../architecture.md) · [Architecture Sinergym](../sinergym-architecture.md)

## 3. Bilan du lot 1 — EnergyPlus

Le lot 1 a livré le modèle monozone de **20 m² et 60 m³**, avec fondation Kiva, infiltration constante, apports d’occupation et trois équipements pilotables. La résistance convective permet d’imposer la puissance de chauffage. La synchronisation DX exploite la charge prédite pour lever la surcharge de vitesse en l’absence de demande de froid. La ventilation équilibrée reste distincte de l’infiltration et de la recirculation DX.

Les commandes, l’occupation et les mesures de zone ont été vérifiées avec le runner direct. L’énergie est agrégée par poste sur les sous-pas finalisés, en respectant la fréquence de chaque variable. Le bilan est rapproché du compteur `Electricity:Facility` dans le CSV natif. [Modèle et conventions physiques](../../models/README.md) · [Procédure de validation directe](../validation.md)

## 4. Bilan du lot 2 — Sinergym et MDP

Le lot 2 a livré la façade `ecobuilding.sinergym_adapter.EcoBuildingEnv`, son worker et le transport action–résultat. Le MDP expose un vecteur **float32 de 20 composantes** et les **27 combinaisons** de `MultiDiscrete([3,3,3])`. La récompense combine l’électricité, les écarts de température, de CO₂ et d’humidité et la variation des commandes. Ses composantes restent accessibles dans `info["reward"]` en mode MDP.

La configuration RL définit sept jours de préparation, sept jours contrôlés, une occupation dynamique et des ensembles Train, Validation et Test séparés jusque dans la préparation. Le plan d’épisodes produit des manifestes d’évaluation fixes et distingue la seed de sélection Train des seeds d’occupation. `gamma=0.99` est un paramètre RL externe à la récompense. [Contrat MDP](../mdp.md) · [Plan d’épisodes](../mdp-episodes.md)

## 5. Synthèse des validations

| Périmètre | Résultat obtenu | Preuve |
|---|---|---|
| EnergyPlus direct, 36.7 | 39 tests unitaires métier et un test d’intégration. Le rejeu final couvre **19 scénarios**, **3 648 pas de zone** et **23 683 sous-pas HVAC**. | [Rapport 36.7, archive locale](../../simulation-outputs/lot1-global-validation/README.md) |
| Sinergym, 37.2.7.5 | **9 tests d’intégration physique réussis**, **59 exécutions à code 0** et **59 états détruits**. Quatre arrêts étaient volontaires. Équivalence exacte pour **14 cas compatibles**, soit **3 072 transitions**, **23 033 sous-pas** et **25 461 lectures DX**. Les 14 paires epJSON et CSV sont identiques octet pour octet. | [Qualification finale, archive locale](../../simulation-outputs/lot2-sinergym-prototype/results/37.2.7.5-final-qualification/qualification-simplifiee/README.md) |
| MDP logiciel, 38.8.4 | **106/106 tests unitaires** réussis. Checkers Gymnasium et Stable-Baselines3 réussis sur le MDP. | [Qualification MDP](../mdp-validation.md) |
| MDP physique, 38.8.5 | Quatre épisodes saisonniers Train et un rejeu hivernal, **3 360 transitions**, **3 365 observations**, 27 actions couvertes par épisode, aucune erreur ou alerte EnergyPlus. Écart électrique maximal **4,66 × 10⁻¹⁰ J** et écart maximal sur la récompense **8,88 × 10⁻¹⁶**. Rejeu hivernal exact sur les traces comparées. | [Synthèse et graphiques dans Git](../mdp-validation.md) · [Traces brutes, archive locale](../../simulation-outputs/38.8.5-mdp/qualification-ekVjnJ/) |

Les campagnes vérifient une simulation, un protocole d’intégration et un calcul de récompense. La 38.8.5 utilise une séquence pseudo-aléatoire de qualification. Les résultats ne sont pas des scores RBC, PPO ou MARL, ni des mesures sur un bâtiment réel.

## 6. Décisions techniques à préserver

| Contrat | Comportement validé |
|---|---|
| État et action | Préserver l’ordre de `STATE_NAMES`, les unités, la forme `(20,)` et le type `float32`. L’action est ordonnée Heating, Cooling, Ventilation, avec niveaux 0, 1 et 2. La demande de vitesse DX reste distincte de l’activation effective. |
| Temporalité et causalité | Un `step` correspond à 900 s. Les mesures intérieures moyennes, l’occupation réelle et l’énergie proviennent de l’intervalle terminé. La récompense utilise la saison de début du pas, y compris au passage à minuit. L’observation représente la fin du pas et ne donne accès à aucun profil futur. |
| Reset et fin | Sept jours de préparation par épisode de qualification. Les cinq valeurs historiques sont nulles au reset. La première action n’entraîne aucun coût de variation. L’amorçage est exclu de la récompense. Après 672 décisions, la fin naturelle confirmée renvoie `terminated=False` et `truncated=True`. Les violations de confort ne déclenchent pas de fin anticipée. |
| Cycle de vie et comptabilité | Demander les variables avant le lancement, résoudre les handles par état et attendre le worker avant destruction. Compter l’électricité de chaque poste une seule fois. Le DX inclut déjà son ventilateur. |
| Reproductibilité et compatibilité | Conserver les fenêtres disjointes entre ensembles, préparation comprise, et le calendrier synthétique. Utiliser les mêmes manifestes d’évaluation pour les futurs agents. Garder `fields=DEFAULT_FIELDS` et `reward_mode="legacy_zero"` pour les rejeux qui s’appuient sur le contrat historique. |

Les plages, seuils, normalisations et poids sont définis dans le contrat MDP et exposés par `RewardConfig`. La consigne DX de 25 °C et les paramètres de ventilation utilisés en qualification restent des hypothèses provisoires. [Récompense et contraintes](../mdp.md#récompense-et-confort) · [Calendrier et manifestes](../mdp-episodes.md)

## 7. Limitations actuelles

- Le bureau est simulé en zone bien mélangée. Le sol, l’infiltration, la ventilation, les performances DX et l’occupation synthétique demandent une calibration pour représenter un site réel. L’humidité est observée sans actionneur indépendant et le contrôle dynamique des ouvertures reste à qualifier.
- Un seul fichier TMYx est utilisé. Les épisodes d’un même ensemble peuvent se chevaucher. L’observation expose une partie de l’état physique et les poids de récompense n’ont pas fait l’objet d’une optimisation par apprentissage.
- Les callbacks privés de Sinergym et leur ordre restent sensibles à une mise à jour. La RSS à long terme reste à caractériser. Le retour non nul après la dernière publication est couvert par doubles dans cette condition précise. Les trois avertissements Gymnasium connus concernent les bornes infinies du Box et l’absence d’EnvSpec. [Limites et justifications](technical-knowledge.md)

## 8. Travaux restants

| Lot | Objectif de reprise | Livrable attendu |
|---|---|---|
| **3 — RBC** | Développer la stratégie à règles sur le contrat MDP existant. | Contrôleur, règles documentées et premières évaluations reproductibles. |
| **4 — PPO** | Développer puis entraîner une politique PPO. | Configuration et exécution reproductibles, modèle appris, résultats Train et Validation documentés. |
| **5 — MARL** | Concevoir et développer un prototype de coordination multi-agent. | Contrat multi-agent à valider, prototype et scénarios de qualification. |
| **6 — Intégration et comparaison** | Évaluer et comparer les stratégies sur un protocole commun. | Résultats appariés, analyses des écarts d’énergie et de confort et bilan d’intégration. |

Les règles RBC, hyperparamètres PPO, responsabilités et mécanismes de coordination MARL restent à décider dans leurs lots respectifs.

## 9. Recommandations de reprise

1. Obtenir le commit de référence et préparer l’image Docker ainsi que l’EPW local. Vérifier les empreintes et les versions depuis les guides. Les preuves hors Git demandent un accès séparé. [Inventaire et prérequis de transmission](inventory.md)
2. Brancher les agents sur le contrat existant. Conserver les versions de configuration et les manifestes associés aux sorties. Distinguer les seeds de l’agent, de sélection et d’occupation. [Exemple d’utilisation](../sinergym-usage.md) · [Relecture des manifestes](../mdp-episodes.md)
3. Convenir des métriques et de la règle de sélection sur Validation avant l’évaluation Test. Comparer les agents sur les mêmes scénarios et rapporter au minimum l’énergie par poste, le confort en occupation et les changements de commande à côté de la récompense cumulée. [Mesures et qualification](../mdp-validation.md)
4. Pour toute évolution de l’adaptateur, contrôler d’abord le contrat avec les tests logiciels, puis choisir une vérification physique adaptée au changement. Conserver le runner direct comme témoin. [Validation Sinergym](../sinergym-validation.md)

## 10. Références documentaires

| Besoin | Point d’entrée |
|---|---|
| Inventorier les fichiers et preuves | [Inventaire de transmission](inventory.md) |
| Comprendre les hypothèses, équations et décisions | [Capitalisation technique](technical-knowledge.md), [modèle EnergyPlus](../../models/README.md), [architecture Sinergym](../sinergym-architecture.md) |
| Installer, lancer et vérifier | [Guide de prise en main](quickstart.md), [README du projet](../../README.md), [usage Sinergym](../sinergym-usage.md), [validation du runner direct](../validation.md) |
| Consulter les configurations | [Référence directe](../../configs/validation/lot1.json), [qualification Sinergym](../../configs/validation/lot2_sinergym.json), [démonstration](../../configs/simulation/sinergym_office.json), [configuration RL](../../configs/rl/office_mdp.json) |
| Consulter les interfaces | [Façade](../../src/ecobuilding/sinergym_adapter/environment.py), [récompense](../../src/ecobuilding/sinergym_adapter/reward.py), [plan d’épisodes](../../src/ecobuilding/episodes.py), [runner direct](../../src/ecobuilding/simulation.py) |
| Retrouver les qualifications | [Vérifications Sinergym](../sinergym-validation.md), [rapport MDP avec figures](../mdp-validation.md), archives signalées en section 5. |

Le [guide de prise en main](quickstart.md) regroupe les commandes destinées aux coéquipiers et les vérifications restantes sur un second poste. La rédaction de `AGENTS.md` pour les agents IA reste à valider.
