# Contrat du MDP EcoBuilding

L’environnement expose une décision HVAC toutes les 15 minutes. L’objectif est de réduire la consommation électrique et les écarts de confort, avec un coût faible pour les changements de commande. EnergyPlus conserve des états internes, dont l’inertie thermique des parois. Le vecteur expose des mesures agrégées et un historique court, sans le profil futur d’occupation ni de météo. Le MDP est donc une approximation d’un système partiellement observable.

## État

`EcoBuildingEnv` renvoie par défaut un `Box` de forme `(20,)` en `float32`, sans normalisation. `STATE_NAMES` fournit l’ordre exact. Les mesures et les diagnostics bruts restent accessibles dans `info["physical"]`.

| Position | Nom | Unité | Source et temporalité |
|---:|---|---|---|
| 1 | `indoor_temperature` | °C | `diagnostics.substep_means.indoor_c`, moyenne pondérée des sous-pas HVAC terminés |
| 2 | `indoor_relative_humidity` | % | `diagnostics.substep_means.indoor_rh_pct`, même moyenne |
| 3 | `indoor_co2` | ppm | `diagnostics.substep_means.co2_ppm`, même moyenne |
| 4 | `outdoor_temperature` | °C | `outdoor.outdoor_c`, rapport de fin de zone |
| 5 | `outdoor_relative_humidity` | % | `outdoor.outdoor_rh_pct`, rapport de fin de zone |
| 6 | `direct_solar_radiation` | W/m² | `outdoor.direct_solar_w_m2`, rapport de fin de zone |
| 7 | `diffuse_solar_radiation` | W/m² | `outdoor.diffuse_solar_w_m2`, rapport de fin de zone |
| 8 | `wind_speed` | m/s | `outdoor.wind_m_s`, rapport de fin de zone |
| 9 | `occupant_count` | personnes | `occupancy.people`, effectif réel de l’intervalle terminé |
| 10 | `hour_sin` | 1 | Sinus de l’heure fractionnaire en fin d’intervalle, période 24 |
| 11 | `hour_cos` | 1 | Cosinus de la même phase |
| 12 | `weekday_sin` | 1 | Sinus du jour de semaine simulé en fin d’intervalle, lundi = 0, période 7 |
| 13 | `weekday_cos` | 1 | Cosinus de la même phase |
| 14 | `day_of_year_sin` | 1 | Sinus de l’indice mois/jour en fin d’intervalle, 1er janvier = 0, période 365 |
| 15 | `day_of_year_cos` | 1 | Cosinus de la même phase |
| 16 | `previous_heating_action` | niveau | Chauffage appliqué à l’intervalle terminé |
| 17 | `previous_cooling_action` | niveau | Cooling appliqué à l’intervalle terminé |
| 18 | `previous_ventilation_action` | niveau | Ventilation appliquée à l’intervalle terminé |
| 19 | `delta_indoor_temperature` | °C | Moyenne intérieure actuelle moins celle de l’observation précédente |
| 20 | `previous_energy_kwh` | kWh | `energy.total_j / 3 600 000` sur l’intervalle terminé |

L’encodage d’un indice `x` de période `p` utilise `sin(2πx/p)` et `cos(2πx/p)`. Un état observé à minuit porte l’heure zéro et le nouveau jour de semaine. La récompense de ce pas utilise le mois du début de l’intervalle, donc celui du jour terminé.

## Actions et transition

`MultiDiscrete([3, 3, 3])` dans l’ordre Heating, Cooling, Ventilation. Les 27 combinaisons sont admissibles à toute heure, y compris chauffage et refroidissement simultanés.

| Niveau | Chauffage électrique | Cooling DX | Ventilation équilibrée |
|---:|---:|---|---:|
| 0 | 0 W | OFF | 0 m³/h |
| 1 | 1 000 W | Vitesse 1, 1,5 kW frigorifiques nominaux | 40 m³/h |
| 2 | 2 000 W | Vitesse 2, 3,5 kW frigorifiques nominaux | 120 m³/h |

Le DX n’active la vitesse demandée qu’en présence d’une charge de refroidissement. Sa puissance dépend des conditions physiques. La consigne de qualification est de 25 °C. Le moteur EnergyPlus simule le prochain intervalle de 900 s après application de l’occupation et des commandes. Sinergym orchestre les callbacks et la façade publie ensuite les mesures agrégées et la récompense. [Architecture du worker et modèle physique](sinergym-architecture.md)

## Récompense et confort

Pour l’intervalle terminé, `e` est l’électricité du chauffage, du DX ventilateur compris et de la ventilation, en kWh. `t`, `c` et `h` sont les moyennes de température, CO₂ et humidité du même intervalle. L’occupation réelle choisit les contraintes.

| Saison | Mois | Plage occupée |
|---|---|---|
| Hiver | Décembre à février | 20–23 °C |
| Printemps | Mars à mai | 20–26 °C |
| Été | Juin à août | 23–26 °C |
| Automne | Septembre à novembre | 20–26 °C |

En inoccupation la plage est de 15–28 °C, avec pénalités CO₂ et HR désactivées. En occupation, le CO₂ est limité à 1 000 ppm et l’HR à 40–60 %.

```text
E = e / 1.0
T = max(0, t_min - t, t - t_max) / 5
β = 3 si occupé, 0.5 sinon
C = max(0, c - 1000) / 1000 si occupé, 0 sinon
H = max(0, 40 - h, h - 60) / 20 si occupé, 0 sinon
A = Σ |a_i - a_précédente_i| / 6 après la première action, 0 au premier pas
reward = -(E + β*T + 2*C + 0.1*H + 0.05*A)
```

Les écarts sont linéaires et non plafonnés. Aucun terme supplémentaire ne pénalise la simultanéité chauffage/Cooling. `info["reward"]` fournit `components`, `weighted`, `total` et `constraints`. `RewardConfig` expose les plages, seuils, facteurs de normalisation et poids.

## Épisodes et compatibilité

Le reset simule sept jours préparatoires, publie les mesures du dernier intervalle préparatoire et remet les cinq valeurs historiques à zéro. La moyenne initiale sert de référence au premier delta. L’énergie préparatoire est exclue de la récompense. Une semaine contrôlée comporte 672 transitions et 673 observations. `terminated` reste False. Le dernier pas renvoie `truncated=True` après confirmation de la sortie moteur à code zéro. Une violation du confort laisse l’épisode se poursuivre. Les erreurs moteur et délais dépassés remontent comme exceptions.

Le facteur d’actualisation externe est `gamma=0.99`. Les manifestes d’évaluation sont communs aux futurs agents RBC et PPO. La projection historique reste accessible via `fields=DEFAULT_FIELDS` et la récompense nulle via `reward_mode="legacy_zero"`.

[Calendrier, seeds et manifestes](mdp-episodes.md) · [Utilisation de la façade](sinergym-usage.md) · [Qualification Gymnasium, SB3 et EnergyPlus](mdp-validation.md)
