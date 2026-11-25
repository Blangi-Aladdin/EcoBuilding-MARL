# Reproduire la validation du bureau

Prérequis locaux. Utiliser Docker avec l’image `ecobuilding-marl:dev`
et EnergyPlus 25.1.0, Python 3.12 et Gymnasium 1.2.3. Sur un autre poste,
construire l’image avec le Dockerfile et les fichiers de dépendances
verrouillées du dépôt si elle est absente. Le modèle local doit correspondre
à la version validée de cette étape.

Extraire l’EPW Belfort-Fontaine TMYx 2011–2025 dans `models/weather/`.
Conserver ce fichier localement en attendant la confirmation des droits de
redistribution. [Archive du fournisseur](https://climate.onebuilding.org/WMO_Region_6_Europe/FRA_France/BF_Bourgogne-Franche-Comte/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.zip)

Depuis la racine du dépôt, vérifier les deux entrées du replay.

```bash
sha256sum -c <<'HASHES'
10bb0cc672e293b3f1f82afc31a38fff38f4795c67c928ef1ffec117383b2bf3  models/office_1zone.epJSON
c3abc4cfd50efc65d6a7bdb7e35c3b7716489f803fc2135747833d6192e6725a  models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw
HASHES
```

## Exécution isolée

Préparer une copie constituée uniquement des entrées et des fichiers
d’exécution. Les résultats sont écrits dans un montage séparé.

```bash
work="$(mktemp -d)"
results="$(mktemp -d)"
mkdir -p "$work/models/weather"
cp -r src configs tests scripts docker "$work/"
cp Dockerfile requirements* .dockerignore "$work/"
cp models/office_1zone.epJSON "$work/models/"
cp models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw "$work/models/weather/"

run_validation() {
  docker run --rm --network none --user "$(id -u):$(id -g)" \
    -v "$work:/project:ro" -v "$results:/results" -w /project \
    -e PYTHONDONTWRITEBYTECODE=1 ecobuilding-marl:dev bash -ec '
      test ! -e /project/simulation-outputs
      export PYTHONPATH="/project/src:$PYTHONPATH"
      exec "$@"
    ' validation "$@"
}

run_validation python docker/check_versions.py
run_validation python -m unittest discover -s tests/unit -v
run_validation env ECOBUILDING_VALIDATION_OUTPUT=/results/full \
  python -m unittest discover -s tests/integration -v
run_validation python scripts/validation/run.py --case matrix-winter --output /results/winter
run_validation python scripts/validation/run.py --weeks --output /results/weeks
```

Exécuter chaque commande avec un nouveau répertoire de résultats pour
conserver les journaux d’un rejeu à l’autre. L’analyse compare les mesures
API et CSV au pas de 15 minutes avec les tolérances absolue de 10⁻⁶ et
relative de 10⁻⁹. L’intégration couvre le natif, les 27 actions dans les deux
saisons, les transitions, les cinq profils d’occupation, les deux vitesses
DX en janvier, la libération, la réinitialisation et un changement de mois.
Les trois semaines comprennent 672 observations chacune, avec seeds 3651
pour les actions et 42 pour l’occupation. Les actions générées servent aux
essais et les cas sont précédés de sept jours d’historique.

Les sorties principales sont `runs.csv`, `semaines.csv`,
`validation-api-csv.csv`, `bilan-energetique.csv` et le catalogue
des observations. Chaque scénario possède ses journaux EnergyPlus, ses
chronologies, ses handles et ses observations. Le critère attendu est zéro
avertissement et zéro erreur sévère.

## Comparaison historique facultative

Les tests et les simulations s’exécutent avec les seuls fichiers de la copie
isolée. Si les anciennes mesures sont présentes localement, comparer les
exports une fois le rejeu terminé.

```bash
python3 scripts/validation/compare_reference.py "$results/full" \
  simulation-outputs/lot1-observation-interface \
  simulation-outputs/lot1-dx-warning-resolution
```

Le comparateur produit `non-regression.csv`. Il compare le contenu des
observations et les mesures HVAC de l’étape 36.6, ainsi que les mesures
communes aux sept cas homologues de l’étape 36.5.1.
