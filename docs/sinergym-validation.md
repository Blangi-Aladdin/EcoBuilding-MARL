# Valider l’intégration Sinergym

Les commandes utilisent la fonction Bash `eb` du [guide d’utilisation](sinergym-usage.md#commandes-docker-et-chemins).

## Niveau 1 — Suite rapide

```bash
eb env PYTHONPATH=/project/tests/unit:/project/src:/usr/local/EnergyPlus-25-1-0 \
  python -m unittest -v test_actions test_cooling test_observations test_occupancy test_simulation
eb python -m unittest discover -s tests/unit/sinergym_adapter -t tests/unit -v
eb python -m unittest discover -s tests/unit -v
```

La suite complète compte 106 tests, dont les tests historiques, les 18 régressions du comparateur et les tests du MDP. Les vérificateurs Gymnasium et SB3 sont exécutés sur la projection historique et sur le MDP. Les doubles exercent notamment la sortie non nulle après le dernier rapport. [Résultats de qualification MDP](mdp-validation.md)

## Niveau 2 — Intégration réelle

Découverte uniquement, sans lancer les tests.

```bash
eb python -c 'import unittest; loader=unittest.TestLoader(); suite=loader.discover("tests/integration"); print(suite.countTestCases()); assert not loader.errors and suite.countTestCases()==9'
```

Commandes physiques préparées pour 37.2.7.5. Le test direct utilise les scénarios de `lot1.json` et le moteur physique. Les huit cas Sinergym qualifient l’amorçage, les six premières transitions janvier A, les journées janvier B et août D, l’occupation G1, la répétition G1/G2, l’interruption T09 et l’équivalence ciblée de janvier `winter-cooling-1`. La classe Sinergym exige l’activation explicite. Avec activation, toute entrée manquante, version incompatible ou sortie inaccessible déclenche une erreur.

```bash
eb python -m unittest discover -s tests/integration -p test_energyplus.py -v
eb env ECOBUILDING_RUN_SINERGYM_INTEGRATION=1 \
  python -m unittest discover -s tests/integration -p test_sinergym_energyplus.py -v
```

[Scénarios et diagnostics EnergyPlus direct](validation.md)

## Niveau 3 — Qualification approfondie

```bash
eb python scripts/validation/run_sinergym_qualification.py --help
eb python scripts/validation/run_sinergym_qualification.py --validate-only
```

Exécuter en 37.2.7.5, après les niveaux 1 et 2.

```bash
eb python scripts/validation/run_sinergym_qualification.py --weekly
eb python scripts/validation/run_sinergym_qualification.py --equivalence
```

La campagne hebdomadaire reprend A–E (17 décembre, 7 août et trois fois 9 octobre), les modes d’occupation natif/natif/dynamique, les graines dynamiques 42/42/123 et la séquence exacte de 672 actions CSV. Le script vérifie son empreinte avant exécution, réutilise la même façade, compare C/D, vérifie la sortie et le nettoyage, et enregistre la RSS maximale. Les interruptions et récupérations essentielles sont couvertes par les cas d’intégration. Les injections détaillées, les blocages contrôlés et la mesure approfondie de threads et descripteurs relèvent des protocoles historiques 37.2.5.6 et 37.2.5.7.

Pour l’équivalence, `lot2_sinergym.json` sélectionne les 14 cas et exclut explicitement les cinq cas hors contrat. Le runner direct construit les séquences, dates, profils, consignes et règles de reporting de `lot1.json`. L’outil vérifie les empreintes historiques des actions puis régénère les 14 références directes dans des dossiers neufs. Les effectifs attendus sont contrôlés avant le rejeu officiel. Les outils de rejeu et de comparaison reprennent l’instrumentation historique, avec harmonisation des seuls objets de reporting dans la copie epJSON d’épisode. Ils comparent observations, sous-pas, prédicteur DX, copies et CSV natifs. Les critères historiques restent `abs_tol=1e-6`, `rel_tol=1e-9` et égalité stricte des variables discrètes. Le rapport indique séparément les identités binaires et les comparaisons numériques exactes. Les métriques et diagnostics sont isolés sous `simulation-outputs/sinergym-runs/qualification/`. Les anciens résultats peuvent servir de témoins supplémentaires lors d’un audit local.

## Portée des résultats historiques

Les sept campagnes 37.2.5 ont vérifié sur le prototype les commandes HVAC, l’occupation dynamique, les épisodes journaliers et hebdomadaires, les resets, les interruptions et les récupérations. En 37.2.6, 19 scénarios ont été examinés et 14 étaient compatibles. Les cinq exclusions concernent des comportements natifs sans action ou la libération d’actionneurs. La campagne a obtenu l’égalité exacte de 3 072 observations contrôlées, 23 033 sous-pas HVAC, 25 461 lectures du prédicteur DX et l’identité binaire des 14 copies epJSON et 14 CSV. L’équivalence du package officiel reste à démontrer en 37.2.7.5.
