## 🛰️ Projet Simulation de Flux de Données du Rover sur Mars

### 🚀 Description
Ce projet simule le flux complet de données réalisé par un rover sur Mars, tel que Curiosity, de la capture des données à la visualisation sur des tableaux de bord interactifs. L'objectif est éducatif et démonstratif, destiné aux étudiants en ingénierie des données, aux startups intéressées par les géodonnées et aux recruteurs d'agences spatiales. La simulation inclut des capteurs, une transmission simulée, un traitement ETL, un stockage analytique, une analyse avec des modèles de machine learning et la visualisation.

---
## 🧱 Architecture Générale
```
[Simulation du Rover] -> [Transmission simulée] -> [Pipeline ETL] -> [Stockage] -> [Modèles ML] -> [Tableau de Bord Web]
```
---
## 🧰 Technologies Utilisées

|Composant | Outils / Technologies |
| --- | --- |
| Simulation de capteurs | Python, Pandas, OpenCV |
| Transmission de données | Kafka (optionnel), Python avec délais et erreurs | 
| Traitement ETL | Apache Airflow, dbt, pandas | 
| Stockage | MinIO / S3, PostgreSQL + PostGIS, Parquet | 
| ML (optionnel) |Scikit-learn, TensorFlow, autoencodeurs | 
| Visualisation | React, Tailwind, Plotly, CesiumJS, Recharts | 
| Infrastructure | Docker, Docker Compose, GitHub Actions (CI/CD) |

## 🧪 Simulation de Données

- **Télémétrie** : Température, batterie, pression, coordonnées
- **Images** : Utilisées depuis l'API de la NASA ou un jeu de données statique
- **Erreurs de transmission** : Simulées avec pertes et retards
---

## 📦 Structure du ProjetBash

```bash
📁 rover-simulacion/
├── data/                  # Données simulées et brutes
├── images/                # Images du rover
├── dashboard/             # Frontend en React
├── backend/               # ETL + API simulées
├── notebooks/             # Analyse exploratoire et ML
├── docker-compose.yml     # Infrastructure locale
├── airflow/               # DAGs pour le traitement
└── README.md              # Ce fichier
```

---
## 🖥️ Comment exécuter le projet

### Prérequis

- Docker et Docker Compose
- Python 3.10+
- Node.js (pour le tableau de bord)

### Étapes

```Bash
# 1. Cloner le dépôt
$ git clone https://github.com/tonutilisateur/rover-simulacion
$ cd rover-simulacion

# 2. Démarrer les services
$ docker-compose up --build

# 3. Accéder au tableau de bord
http://localhost:3000

# 4. Accéder à Airflow pour voir le pipeline
http://localhost:8080 (utilisateur : admin, mot de passe : admin)
```

---

## 📊 Visualisation

- **Tableau de bord web** avec télémétrie, trajet du rover et galerie d'images
- **Graphiques interactifs** avec Recharts et cartes avec CesiumJS
---
## 🤖 Modèles de ML (optionnel)
- Classification de terrain
- Prédiction de pannes
- Détection d'anomalies des capteurs

---
## 🎯 Objectifs éducatifs
- Apprendre à construire des pipelines ETL complexes
- Intégrer géodonnées et images dans un seul système
- Se familiariser avec les technologies de données utilisées dans l'exploration spatiale
---
## 🤝 Contributions et licences
- Code sous licence MIT
- Vous pouvez ouvrir des issues ou des pull requests
---
## 🌌 Crédits
- NASA Open API
- ESA Planetary Data Archive
- Communauté des données spatiales ouvertes
---
📬 Contact
Si vous êtes recruteur, éducateur ou une agence intéressée, vous pouvez me contacter à javierladino@me.com

Explorez Mars, en construisant depuis la Terre !