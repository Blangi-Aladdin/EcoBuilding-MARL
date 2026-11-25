# Consignes de contribution à EcoBuilding-MARL

Ces consignes s’adressent aux développeurs et aux agents IA capables de lire le dépôt. Si votre outil ne charge pas automatiquement ce fichier, ouvrez-le explicitement au début de l’intervention.

## A. Contexte et objectifs

EcoBuilding-MARL étudie le compromis entre consommation électrique, confort thermique et qualité de l’air dans un bureau monozone. Le lot 1 livre le modèle EnergyPlus pilotable et son parcours de validation directe. Le lot 2 livre l’intégration Sinergym et l’environnement Gymnasium du MDP. Ces deux lots sont qualifiés en simulation.

Les lots suivants portent sur le contrôle à règles (lot 3), PPO (lot 4), le prototype multi-agent (lot 5) et la comparaison des stratégies (lot 6). Les décisions de conception de ces lots relèvent de leurs équipes. [Rapport de transmission](docs/handover/handover.md)

## B. Parcours de découverte

1. Lire le [README](README.md) pour le périmètre, la branche et la version de référence.
2. Lire le [rapport de transmission](docs/handover/handover.md) pour les acquis, les limites et les travaux restants.
3. Utiliser le [guide de prise en main](docs/handover/quickstart.md) pour préparer le poste et découvrir le parcours MDP.
4. Consulter l’[inventaire](docs/handover/inventory.md) pour retrouver les livrables et les preuves accessibles séparément.
5. Lire la [capitalisation technique](docs/handover/technical-knowledge.md) pour les justifications, les interfaces du lot 3 et les erreurs à éviter. Utiliser ensuite les sources spécialisées correspondant au changement.

## C. Architecture et environnement technique

| Composant | Responsabilité et référence |
| --- | --- |
| [`models/office_1zone.epJSON`](models/office_1zone.epJSON) et [`src/ecobuilding/`](src/ecobuilding/) | EnergyPlus calcule la physique. Le code métier gère les commandes HVAC, l’occupation et les observations. Le runner direct sert à produire les références. [Architecture EnergyPlus](docs/architecture.md) |
| [`sinergym_adapter/`](src/ecobuilding/sinergym_adapter/) | Sinergym orchestre le worker EnergyPlus. Le transport associe chaque action à son résultat. `EcoBuildingEnv` expose l’interface Gymnasium, l’état et la récompense. [Architecture Sinergym](docs/sinergym-architecture.md) |
| [`configs/`](configs/), [`scripts/`](scripts/) et [`tests/`](tests/) | Configurations d’épisodes et de qualification, lanceurs, comparateurs et suites de tests. |
| [Dockerfile](Dockerfile), [dépendances verrouillées](requirements.lock), [dépendances de build](requirements-build.lock) et [Dev Container](.devcontainer/devcontainer.json) | Environnement `linux/amd64` des qualifications. Les versions de référence et leur contrôle figurent dans le [guide Sinergym](docs/sinergym-usage.md). |

## D. Préservation des acquis techniques

- Conserver `cec22b6a076da718d05f7b2bc1559c3feae9bcd0` comme référence technique qualifiée. Justifier et requalifier tout changement qui affecte le modèle, les mesures, les commandes, la récompense ou le cycle de vie.
- Préserver `EcoBuildingEnv.reset/step/close`, l’ordre de `STATE_NAMES`, le `Box` de forme `(20,)` en `float32` et l’ordre chauffage, refroidissement et ventilation (`Heating`, `Cooling`, `Ventilation`) de `MultiDiscrete([3, 3, 3])`. Distinguer demande, commande appliquée et effet physique. Préserver les diagnostics `info["physical"]` et les composantes `info["reward"]` du mode MDP.
- Préserver la causalité. Les observations décrivent le dernier intervalle terminé et la récompense utilise sa saison au début du pas. Respecter les unités, les agrégations et le bilan sans double comptage. Réserver `legacy_zero` aux rejeux historiques concernés. [Contrat MDP](docs/mdp.md)
- Préserver la séparation météo Train, Validation et Test, préparation comprise, et rejouer les mêmes manifestes pour comparer les agents. Garder Test pour l’évaluation finale et distinguer les seeds de sélection, d’occupation et d’agent. [Plan des épisodes](docs/mdp-episodes.md)
- Préserver l’ordre des callbacks, la résolution des handles par état et la fermeture du worker avant destruction de l’état EnergyPlus. Appeler `close()` dans un bloc `finally`. [Cycle de vie](docs/sinergym-architecture.md#cycle-et-contrat-temporel)

## E. Règles de développement

- Examiner les sources, la documentation et les tests concernés avant toute modification. Réutiliser les interfaces existantes et limiter le changement au besoin du lot.
- Expliquer les décisions nouvelles, leurs hypothèses et leur incidence sur les contrats. Ajouter ou adapter les tests quand le changement touche un comportement que la suite ne couvre pas.
- Distinguer observations, hypothèses, résultats mesurés et limites de validation. Indiquer la preuve ou l’incertitude pour chaque résultat important.

## F. Tests et validation

Depuis la racine du dépôt, préparer l’environnement selon le [guide de prise en main](docs/handover/quickstart.md#6-tester-et-reproduire-les-qualifications). La commande `eb python -m unittest discover -s tests/unit -v` utilise la fonction Docker `eb` définie dans ce guide.

Les tests d’intégration lancent de vraies simulations. Le guide donne les commandes du runner direct et l’activation explicite des tests Sinergym. Choisir les vérifications selon l’impact du changement. Rejouer une campagne historique quand une modification remet en jeu ce qu’elle vérifie. Consigner la configuration, les versions, les scénarios, les seeds et les résultats utilisés. [Validation EnergyPlus](docs/validation.md) · [Validation Sinergym](docs/sinergym-validation.md) · [Qualification MDP](docs/mdp-validation.md)

## G. Gestion Git et collaboration

- Vérifier la branche, le statut et le périmètre du diff. Préserver les travaux existants et utiliser une branche adaptée au changement. La branche de transmission des lots 1 et 2 est `feature/lot1-lot2-building-environment`.
- Préparer des commits cohérents et traçables. Indexer les chemins concernés et vérifier le diff de l’index, notamment avec `git diff --cached --check`.
- Les agents IA ne doivent pas effectuer de commit, de push ou de création de Pull Request sans autorisation explicite du développeur responsable de l’intervention. Cette règle s’applique aux agents IA et ne restreint pas les opérations réalisées directement par les développeurs.
- Obtenir l’autorisation avant un merge, une suppression de branche ou un force push. Exclure des publications les secrets, les fichiers temporaires, l’EPW et les résultats bruts de simulation.

## H. Ressources externes et limitations

- Récupérer l’EPW Belfort–Fontaine selon le guide et vérifier son empreinte. Construire ou obtenir l’image `ecobuilding-marl:dev`. Vérifier l’installation sur le poste destinataire. [Préparation du poste et des entrées](docs/handover/quickstart.md#3-installer-lenvironnement-et-préparer-la-météo)
- Demander au groupe les archives de qualification nécessaires à une vérification indépendante. Les résultats bruts sous `simulation-outputs/` restent hors Git. [Inventaire des preuves](docs/handover/inventory.md#5-inventaire-des-preuves-de-validation)
- Le périmètre qualifié est d’une simulation active par processus. Le bureau est une zone bien mélangée, avec un TMYx unique, des paramètres physiques provisoires et une occupation synthétique. Les qualifications établissent le comportement de la simulation et de ses interfaces. La calibration sur un bâtiment réel et la performance des stratégies restent à établir. [Limites techniques](docs/handover/technical-knowledge.md#9-limites-et-perspectives)
