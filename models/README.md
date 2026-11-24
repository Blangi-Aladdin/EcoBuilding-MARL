# Lot 1 — Bureau monozone à Belfort

Le modèle [office_1zone.epJSON](office_1zone.epJSON) cible EnergyPlus
**25.1.0** (build `1c11a3d85f`) dans l’image `ecobuilding-marl:dev`.

## Hypothèses

| Élément | Modèle |
|---|---|
| Géométrie | Une zone de **5 × 4 × 3 m**, soit **20 m²** et **60 m³**. Quatre murs extérieurs, toiture plate et dalle sur terre-plein. L’axe X pointe vers l’est et l’axe Y vers le nord. |
| Fenêtre | Au sud, **1,50 × 1,20 m**, allège à **0,90 m**. Double vitrage équivalent avec `U = 1,6 W/(m²·K)` et `SHGC = 0,55`. |
| Porte | Au nord, porte opaque en bois de **0,90 × 2,10 m** et **45 mm** d’épaisseur. Le bas de la porte est à **1 cm** de la dalle pour garder le contour dans la façade. |
| Parois | Mur en maçonnerie de **200 mm** avec **100 mm** de laine minérale. Toiture en béton de **150 mm** avec **160 mm** de laine minérale. Dalle en béton de **150 mm** avec **80 mm** d’isolant rigide. |
| Sol | Condition `Foundation` avec Kiva au pas de **15 minutes**. Les quatre côtés de la dalle sont exposés, soit **18 m**. |
| Infiltration | **0,2 vol/h** en continu (12 m³/h au débit nominal). Aucun débit mécanique ni ouverture de fenêtre modélisés. |
| Occupation | **Deux personnes**, **120 W/personne**, du lundi au vendredi de **08:00 à 18:00** en heure locale standard. Week-ends inoccupés. Aucun jour férié distinct, éclairage artificiel ou équipement de bureau n'est modélisé. |
| Chauffage | Plinthe électrique convective, **2 kW** nominaux, rendement **1,0**. Consigne **21 °C** en occupation et **16 °C** hors occupation. Aucun refroidissement. |
| Temps | Quatre pas de zone par heure. La période d’essai est le **27 janvier** avec un calendrier fixant ce jour au lundi pour exercer les deux consignes. |

## Infiltration et CO₂

Le bilan de contaminants d’EnergyPlus calcule la concentration moyenne de
CO₂ dans la zone. Le CO₂ extérieur est fixé à **420 ppm** à titre d’hypothèse,
sans mesure locale. Les deux occupants conservent leur activité de bureau de
**120 W/personne**. Le coefficient par défaut EnergyPlus, explicité dans
le modèle, vaut **3,82 × 10⁻⁸ m³/(s·W)**, soit **4,584 mL/s par personne**
et **9,168 mL/s** au total en occupation. Le débit émis est nul hors
occupation. [Référence EnergyPlus 25.1 sur les occupants](https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-internal-gains-people-lights-other.html)

Le renouvellement d’air se limite à l’infiltration constante. La zone
suppose un air bien mélangé. L’indicateur CO₂ ne couvre pas les autres
polluants et ne suffit pas à attester la qualité de l’air du bureau.
Les concentrations de début de journée dépendent du préchauffage du modèle
et de son historique simulé. Les résultats de cette journée sont une
comparaison de scénarios, sans extrapolation annuelle.

L’essai du 27 janvier avec le même EPW a comparé **0,2 vol/h** à **0,5 vol/h**
avec le même bilan CO₂. Le CSV de référence historique ne contenait pas
cette variable. La référence réexécutée reproduit à chaque pas la
température et l’énergie de chauffage de l’essai historique.

| Indicateur | Référence 0,5 vol/h | Cas 0,2 vol/h |
|---|---:|---:|
| CO₂ en occupation, moyenne / maximum | 1 251 / 1 459 ppm | 1 960 / 2 706 ppm |
| CO₂ avant 08:00, plage | 421–473 ppm | 561–1 108 ppm |
| CO₂ après 18:00, plage | 480–1 394 ppm | 1 168–2 646 ppm |
| Température intérieure, plage | 16–21 °C | 16–21 °C |
| Électricité de chauffage sur 24 h | 11,086 kWh | 9,716 kWh |

## Humidité et apports des occupants

Le champ `sensible_heat_fraction` de l’objet `People` conserve sa valeur
par défaut `Autocalculate`. À chaque pas occupé, EnergyPlus répartit les
**240 W** des deux occupants entre chaleur sensible et latente selon leur
activité et la température de zone. Les **30 % radiants** s’appliquent
uniquement à la part sensible. Sur la journée testée, les moyennes en
occupation sont **166,2 W sensibles (69,2 %)** et **73,8 W latents (30,8 %)**.
Les deux apports sont nuls hors occupation.
[Référence EnergyPlus 25.1 sur les occupants](https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-internal-gains-people-lights-other.html)

Les résultats à 15 minutes incluent l’humidité relative intérieure et
extérieure, les températures, le CO₂, l’électricité du chauffage et le
rapport d’humidité, exprimé en masse d’eau par masse d’air sec. Ce rapport
permet de distinguer un apport ou un retrait de vapeur d’une variation
d’humidité relative causée par la température. Les copies ventilées
rapportent également le débit mécanique à la densité de l’air extérieur.
[Référence EnergyPlus 25.1 sur l’humidité de zone](https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-thermal-zone-description-geometry.html)

Le lundi 27 janvier, deux copies utilisent un apport et une extraction
équilibrés de **40** et **60 m³/h**, actifs de **08:00 à 18:00**.
L’infiltration de **0,2 vol/h** reste active en permanence. Ces essais
intègrent l’effet thermique de l’air neuf. Ils ne comprennent ni
récupération de chaleur ni consommation électrique des ventilateurs.

| Débit mécanique | HR intérieure sur 24 h | HR moyenne en occupation | Durée hors 40–60 % | CO₂ moyen / max. en occupation | Électricité du chauffage |
|---:|---:|---:|---:|---:|---:|
| 0 m³/h | 42,6–98,5 % | 66,7 % | 14 h 30 au-dessus de 60 % | 1 960 / 2 706 ppm | 9,716 kWh |
| 40 m³/h | 41,1–58,8 % | 49,5 % | 0 h | 954 / 1 027 ppm | 11,173 kWh |
| 60 m³/h | 41,1–54,7 % | 47,1 % | 0 h | 819 / 859 ppm | 11,970 kWh |

Sans ventilation mécanique, les pas au-dessus de 60 % couvrent
**00:00–01:00** et **10:30–24:00**, dont **7 h 30** en occupation.
L’extérieur affiche **75–90 % HR**, mais sa teneur en vapeur est de
**5,09–7,10 g/kg d’air sec**. À 18:00, l’air intérieur sans ventilation
atteint **12,35 g/kg**, contre **7,06** et **6,52 g/kg** à 40 et 60 m³/h.
Les concentrations et l’humidité matinales dépendent de l’initialisation.
Le modèle suppose une zone bien mélangée, sans régulation d’humidité ni
tampon hygroscopique des matériaux. Le pic de 98,5 % est un résultat du
bilan de zone. Il ne permet pas de conclure sur une éventuelle condensation
sur les surfaces. Une seule journée hivernale ne permet pas de
généraliser ces résultats aux autres saisons.

## Échanges avec le terrain

Kiva calcule les échanges transitoires entre la zone et le terrain à partir
de la coupe de la fondation, du périmètre exposé et de la météo. Cette méthode
remplace les températures mensuelles imposées et permet de conserver la dalle
de 5 × 4 m après les difficultés de maillage rencontrées avec Slab.
L’isolant de 80 mm reste dans la construction du plancher, sous les 150 mm de
béton. Aucune isolation de rive ni semelle explicite n’a été ajoutée.

Pour ce premier modèle, le dessus de la dalle est supposé à **0,20 m**
au-dessus du terrain extérieur, avec **0 m** de prolongement du mur de
fondation sous la dalle et une construction de rive par défaut. La
température intérieure d’initialisation est laissée à l’estimation de Kiva
d’après les consignes de zone. Les propriétés de sol par défaut sont
**1,73 W/(m·K)**, **1 842 kg/m³** et **419 J/(kg·K)**. La condition profonde
est `Autoselect` avec profondeur `Autocalculate`. Ces paramètres sont
provisoires et aucune mesure géotechnique du site ne les confirme.

Kiva utilise une représentation bidimensionnelle de la fondation. Le flux
calculé est sensible aux propriétés du terrain et aux détails de rive.
Kiva initialise le terrain à partir de l’historique de l’EPW. Un essai de
24 heures vérifiera le fonctionnement du modèle, tandis que la pertinence
des hypothèses de sol demande des données du site. Les sorties de face
extérieure de la dalle sont indisponibles avec la condition `Foundation`.
[Référence Kiva pour EnergyPlus 25.1](https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-advanced-surface-concepts.html)

## Météo

Fichier horaire **Belfort–Fontaine TMYx 2011–2025**, identifiant
`072960`, latitude **47,59170° N**, longitude **6,83690° E**,
altitude **402 m**, fuseau **UTC+1**. L’en-tête indique une année
météorologique type construite à partir de NCEI ISD et ERA5.
Le fichier a été extrait tel quel de l’archive et contient
**8 760 enregistrements horaires**. Le fournisseur indique `0` dans
la colonne des minutes pour toutes les lignes. Le premier essai vérifiera
la lecture du fichier par EnergyPlus.
[Archive du fournisseur](https://climate.onebuilding.org/WMO_Region_6_Europe/FRA_France/BF_Bourgogne-Franche-Comte/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.zip)

SHA-256 du fichier EPW :

```text
c3abc4cfd50efc65d6a7bdb7e35c3b7716489f803fc2135747833d6192e6725a
```

## Énergie de la ventilation équilibrée

`Balanced outdoor air` utilise deux ventilateurs identiques dans
`ZoneVentilation:DesignFlowRate`. La hausse de pression est de **150 Pa par
ventilateur** et le rendement global moteur–roue est de **50 %**.
Pour un débit d’air neuf \(Q\) en m³/s à la densité extérieure,
la puissance électrique totale vaut `2 × Q × Δp / η`, soit 0,167 Wh/m³.
EnergyPlus applique à l’air entrant la chaleur du seul ventilateur de
soufflage, égale à la moitié de la puissance électrique totale.
[Documentation EnergyPlus 25.1](https://bigladdersoftware.com/epx/docs/25-1/input-output-reference/group-airflow.html)

| Action | Niveau | Débit | Puissance électrique totale | Énergie par 15 min |
| --- | --- | ---: | ---: | ---: |
| 0 | OFF | 0 m³/h | 0 W | 0 J |
| 1 | MEDIUM | 40 m³/h | 6,67 W | 6 000 J |
| 2 | HIGH | 120 m³/h | 20 W | 18 000 J |

Les débits MEDIUM et HIGH restent provisoires. Pression et rendement
constants sont des hypothèses de simulation validées expérimentalement
dans EnergyPlus. Le modèle suppose une veille de 0 W et aucune récupération
de chaleur. Les paramètres pourront être recalibrés à partir des mesures
d’un équipement et de son réseau. Le débit de ventilation est piloté
indépendamment du DX. L’air recirculé du DX et l’infiltration de 0,2 vol/h
ont leurs propres observations.

| Variable EnergyPlus, clé `OFFICE` | Unité | Rapport `Timestep` |
| --- | --- | --- |
| `Zone Ventilation Fan Electricity Energy` | J | Somme des sous-pas HVAC |
| `Zone Ventilation Outdoor Density Volume Flow Rate` | m³/s | Moyenne sur le pas de zone |
| `Zone Ventilation Air Inlet Temperature` | °C | Moyenne sur le pas de zone |

Pour une future intégration Sinergym, demander les variables avec
`request_variable` avant la simulation et obtenir leurs handles lorsque
`api_data_fully_ready` est vrai. Lire l’énergie à chaque
`callback_end_system_timestep_after_hvac_reporting`, sommer les joules sur
les sous-pas HVAC du pas de zone de **15 minutes**, puis remettre
l’accumulateur à zéro. Diviser par 3 600 000 pour obtenir des kWh. Une
lecture unique en fin de pas de zone ne couvre que le dernier sous-pas
HVAC lorsque le moteur subdivise le pas.

Pour un bilan par poste, additionner l’énergie électrique de la plinthe,
celle de l’unité DX (ventilateur déjà inclus) et celle de la ventilation.
Dans les CSV EnergyPlus, `Ventilation (simple):Fans:Electricity` recouvre
la variable de ventilation, `Fans:Electricity` regroupe aussi le
ventilateur DX et `Electricity:Facility` inclut déjà ces postes. Utiliser
ces compteurs pour le rapprochement, en comptant chaque poste une seule
fois. Sur le build EnergyPlus 25.1.0 utilisé, le handle API de
`Electricity:Facility` renvoie `-1` malgré sa présence dans l’inventaire.
Le bilan global est vérifié avec `eplusmtr.csv`.
[Code source de la lecture des compteurs](https://github.com/NatLabRockies/EnergyPlus/blob/v25.1.0/src/EnergyPlus/api/datatransfer.cc#L362-L378)

## Validation

Les commandes suivantes s’exécutent depuis la racine du dépôt. La conversion
seule vérifie qu’EnergyPlus 25.1.0 peut lire le modèle. Le fichier IDF généré
disparaît avec le conteneur.

```bash
docker run --rm --network none --read-only --tmpfs /tmp \
  --mount "type=bind,source=$PWD/models,target=/input,readonly" \
  ecobuilding-marl:dev sh -ec '
    cp /input/office_1zone.epJSON /tmp/office_1zone.epJSON
    energyplus --convert-only -d /tmp /tmp/office_1zone.epJSON
    test -s /tmp/office_1zone.idf
  '
```

Le modèle a également été contrôlé contre `Energy+.schema.epJSON` de cette
version. Le contrôle géométrique a vérifié six faces avec des normales
sortantes, douze arêtes partagées, un volume fermé de 60 m³, un plancher de
20 m² et deux ouvertures coplanaires strictement à l’intérieur de leur façade.

### Essai de 24 heures après validation

```bash
mkdir -p simulation-outputs/lot1-office
docker run --rm --network none \
  --mount "type=bind,source=$PWD/models,target=/input,readonly" \
  --mount "type=bind,source=$PWD/simulation-outputs/lot1-office,target=/output" \
  ecobuilding-marl:dev energyplus -d /output \
  -w /input/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw \
  /input/office_1zone.epJSON
```

Examiner `eplusout.err` pour repérer les erreurs et avertissements, puis
`eplusout.csv` pour vérifier les 96 pas de zone, la température intérieure,
les horaires d’occupation, les consignes, le CO₂ en ppm et l’énergie
électrique du chauffage en joules par pas (diviser par 3 600 000 pour
obtenir des kWh).
L’essai devra confirmer la lecture effective de la météo et montrer si
la plinthe atteint la consigne lorsque sa puissance plafonne à 2 kW.
