## 🛰️ Projet Simulation de Flux de Données du Rover sur Mars

### 🚀 Description
Ce projet simule le flux complet de données réalisé par un rover sur Mars, tel que Curiosity, de la capture des données à la visualisation sur des tableaux de bord interactifs. L'objectif est éducatif et démonstratif, destiné aux étudiants en ingénierie des données, aux startups intéressées par les géodonnées et aux recruteurs d'agences spatiales.La simulation inclut des capteurs, une transmission simulée, un traitement ETL, un stockage analytique, une analyse avec des modèles de machine learning et la visualisation.🧱 Architecture Générale[Simulation du Rover] -> [Transmission simulée] -> [Pipeline ETL] -> [Stockage] -> [Modèles ML] -> [Tableau de Bord Web]

### 🧰 Technologies Utilisées

ComposantOutils / TechnologiesSimulation de capteursPython, Pandas, OpenCVTransmission de donnéesKafka (optionnel), Python avec délais et erreursTraitement ETLApache Airflow, PySparkStockageMinIO / S3, PostgreSQL + PostGIS, ParquetML (optionnel)Scikit-learn, TensorFlow, autoencodeursVisualisationReact, Tailwind, Plotly, CesiumJS, RechartsInfrastructureDocker, Docker Compose, GitHub Actions (CI/CD)🧪 Simulation de DonnéesTélémétrie : Température, batterie, pression, coordonnéesImages : Utilisées depuis l'API de la NASA ou un jeu de données statiqueErreurs de transmission : Simulées avec pertes et retards📦 Structure du ProjetBash📁 rover-simulacion/
├── data/                  # Données simulées et brutes
├── images/                # Images du rover
├── dashboard/             # Frontend en React
├── backend/               # ETL + API simulées
├── notebooks/             # Analyse exploratoire et ML
├── docker-compose.yml     # Infrastructure locale
├── airflow/               # DAGs pour le traitement
└── README.md              # Ce fichier

🖥️ Comment exécuter le projetPrérequisDocker et Docker ComposePython 3.10+Node.js (pour le tableau de bord)ÉtapesBash# 1. Cloner le dépôt
$ git clone https://github.com/tonutilisateur/rover-simulacion
$ cd rover-simulacion

# 2. Démarrer les services
$ docker-compose up --build

# 3. Accéder au tableau de bord
http://localhost:3000

# 4. Accéder à Airflow pour voir le pipeline
http://localhost:8080 (utilisateur : admin, mot de passe : admin)

📊 VisualisationTableau de bord web avec télémétrie, trajet du rover et galerie d'imagesGraphiques interactifs avec Recharts et cartes avec CesiumJS🤖 Modèles de ML (optionnel)Classification de terrainPrédiction de pannesDétection d'anomalies des capteurs🎯 Objectifs éducatifsApprendre à construire des pipelines ETL complexesIntégrer géodonnées et images dans un seul systèmeSe familiariser avec les technologies de données utilisées dans l'exploration spatiale🤝 Contributions et licencesCode sous licence MITVous pouvez ouvrir des issues ou des pull requests🌌 CréditsNASA Open APIESA Planetary Data ArchiveCommunauté des données spatiales ouvertes📬 ContactSi vous êtes recruteur, éducateur ou une agence intéressée, vous pouvez me contacter à javierladino@me.comExplorez Mars, en construisant depuis la Terre !