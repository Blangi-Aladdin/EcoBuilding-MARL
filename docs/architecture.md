# Architecture de validation EnergyPlus

| Module sous `src/ecobuilding/` | Responsabilité |
|---|---|
| `actions.py` | Validation du vecteur HVAC complet, liaison par état, écritures, mémorisation, arrêt et libération |
| `cooling.py`, `_cooling_base.py` | Commande DX corrigée et opérations communes de liaison, arrêt et libération |
| `occupancy.py` | Application exogène, mesure et libération de l’occupation |
| `occupancy_profiles.py` | Profil natif de référence, scénarios déterministes et profils générés par seed |
| `observations.py` | Catalogue API, validation, horodatage, agrégation et instantané du pas terminé |
| `simulation.py` | Création de l’état, copie instrumentée du modèle, callbacks, exports et nettoyage |

Le modèle physique suivi par Git définit les caractéristiques du bâtiment et
des équipements. La configuration JSON sous `configs/validation/` porte les
paramètres de rejeu. Le package s’importe depuis `src` via `PYTHONPATH`,
en préservant le chemin de l’API EnergyPlus de l’image.

## Commandes HVAC

L’espace `MultiDiscrete([3, 3, 3])` contient 27 combinaisons, ordonnées
`[Heating, Cooling, Ventilation]`. Le contrôleur vérifie les trois indices
entiers avant toute écriture et accepte les vecteurs NumPy. Une erreur API
partielle bloque le contrôleur pour l’état courant. `all_off()` impose le
vecteur nul. `release()` rend la commande au modèle et garde la dernière
action dans l’historique.

| Poste | OFF | MEDIUM | HIGH | Actionnement |
|---|---:|---:|---:|---|
| Chauffage | 0 W | 1 000 W | 2 000 W | `Schedule:Constant / Schedule Value / OFFICE HEATING POWER FRACTION` avec fractions 0, 0,5 et 1 |
| Cooling | Arrêt | Vitesse 1, nominal 1 500 W | Vitesse 2, nominal 3 500 W | Disponibilité `DX SCHEDULED AVAILABILITY`, vitesse `OFFICE DX UNIT` et consigne `SUMMER COOLING SETPOINT` |
| Ventilation | 0 m³/h | 40 m³/h | 120 m³/h | `Zone Ventilation / Air Exchange Flow Rate / BALANCED OUTDOOR AIR` en m³/s |

Après le prédicteur, la commande Cooling lit `Zone Predicted Sensible Load
to Setpoint Heat Transfer Rate` pour `OFFICE`. Une charge négative autorise
la vitesse mémorisée. À charge nulle ou positive, la surcharge de vitesse
est libérée. Cooling OFF impose l’arrêt. Le prédicteur peut être rappelé au
cours du pas. La capacité thermique effective dépend des conditions
physiques. Les trois commandes sont indépendantes des horaires, de
l’occupation et de la saison. La consigne technique de 25 °C et les débits
de ventilation MEDIUM et HIGH restent provisoires.

## Occupation et chronologie

L’occupation native suit le schedule du modèle. La commande
`Schedule:Compact / Schedule Value / OFFICE OCCUPANCY` convertit
0, 1 ou 2 personnes en fractions 0, 0,5 ou 1. Les profils déterministes
couvrent notamment la pause déjeuner, l’arrivée anticipée, le départ
tardif, le samedi et les transitions rapides. Le générateur conserve ses
probabilités expérimentales de 65 % d’absence au déjeuner par personne,
15 % de journée de semaine vide et 35 % de visite le week-end. La seed de
rejeu est 42. Ces probabilités restent à calibrer sur des données réelles.

1. `begin_zone_timestep_before_set_current_weather` initialise les handles et applique l’occupation du pas entrant.
2. `begin_zone_timestep_before_init_heat_balance` applique l’action de validation. L’observation disponible à ce point appartient au pas terminé. L’effectif observé peut donc avoir 15 minutes de retard sur le profil appliqué.
3. `after_predictor_after_hvac_managers` synchronise la vitesse DX avec la charge courante.
4. `end_system_timestep_after_hvac_reporting` collecte les mesures HVAC finalisées, avec leur durée réelle.
5. `end_zone_timestep_after_zone_reporting` publie l’observation complète puis libère les actionneurs si le scénario le demande.

Les profils sont des entrées exogènes du coordinateur. L’interface des
observations expose uniquement le présent et le dernier pas terminé. Le
warmup et l’historique préparatoire sont exclus de la collecte et des
surcharges. Chaque simulation alloue un état neuf. En fin d’exécution ou en
cas d’échec, le coordinateur détache les gestionnaires, efface les callbacks
et supprime l’état. Les replays du processus sont séquentiels.

## Observations et énergie

Le catalogue `VARIABLES` du module [observations.py](../src/ecobuilding/observations.py)
définit le nom EnergyPlus, la clé, l’unité, la règle d’agrégation, le rôle et
le caractère optionnel des 27 variables. Le replay exporte ce catalogue
dans `catalogue-observations.csv`. Les groupes publics sont `time`,
`indoor`, `outdoor`, `occupancy`, `actions`, `equipment`, `energy`
et `diagnostics`. Les handles obligatoires sont vérifiés par état. Les deux
variables optionnelles d’énergie de la bobine et du ventilateur DX sont
représentées par `None` si elles sont indisponibles. Les diagnostics
incluent les mesures de rapprochement et le contexte de prédiction. Le
candidat numérique nommé reste expérimental.

L’horodatage contient le début et la fin normalisés du pas de zone, bâtis
avec l’année calendaire et l’indice du pas EnergyPlus. Le millésime TMYx
décrit la provenance météo. La température de zone publiée est lue au
rapport de zone. L’humidité et le CO₂ sont pondérés par les durées HVAC.
L’effectif et les conditions extérieures sont lus en fin de zone. La vitesse
DX effective désigne les étages observés pendant la production de froid.

La somme électrique du modèle est `E_total = E_heating + E_cooling_DX +
E_ventilation`.

- Chauffage électrique. Lecture unique en fin de zone, rapprochée de l’intégrale de puissance.
- Cooling. Intégration de la puissance électrique de l’unité, ventilateur DX compris, sur les intervalles HVAC finalisés. Les énergies de bobine et de ventilateur servent au rapprochement.
- Ventilation équilibrée. Somme des joules de chaque sous-pas finalisé. Les niveaux donnent 0, 6,67 et 20 W avec 150 Pa et 50 % de rendement. Le débit d’air neuf et l’infiltration sont mesurés séparément.

Les conversions sont `E_kWh = E_J / 3_600_000` et
`P_moyenne_W = E_kWh × 1000 / durée_du_pas_en_heures`. Le replay compare
chaque somme à `Electricity:Facility` dans les CSV. Dans EnergyPlus 25.1.0,
le compteur a l’indice interne 0, alors que son handle nommé retourne −1.
Le package utilise la somme des trois postes. Tout nouveau consommateur
électrique devra être intégré à cette somme. [Diagnostic et modèle énergétique](../models/README.md)

L’architecture couvre actuellement une zone. L’année bissextile est testée
dans les fonctions temporelles et le changement de mois en simulation. Les
replays bissextiles et les changements d’heure restent à qualifier. Les
intégrations Sinergym, RBC, PPO et MARL restent à réaliser pour ce modèle.
