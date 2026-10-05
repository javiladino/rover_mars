> **Documento histórico.** Borrador inicial de planificación; el stack real está en el README.

# rover_mars

## 🚀 Visión general del proyecto

**Objetivo:** Simular el flujo de datos de un rover en Marte, desde sensores hasta dashboards interactivos, usando datos reales o generados, replicando la infraestructura y procesos usados por NASA o ESA.

**Aplicación:** Formación en ingeniería de datos, showcase técnico, demostrador para startups.

---

## 🧪 PASO A PASO PARA SIMULAR TODO EL SISTEMA

### 🛠️ 1. **Simulación del rover**

### A. Emulación de sensores

- Generar datos sintéticos con scripts (Python): temperatura, presión, posición GPS simulada (lat/long marcianas), salud del sistema, imágenes (pueden ser reales de NASA).
- O usar un robot terrestre (Raspberry Pi + sensores) si es una demo física.

### B. Imágenes y videos

- Usar el API pública de la NASA: Mars Rover Photos
- O cargar imágenes descargadas desde mars.nasa.gov

---

### 📡 2. **Simulación de la transmisión**

### A. Latencia y errores

- Simula la latencia (~10 minutos) usando colas de mensajes (Kafka, RabbitMQ) con delay.
- Simula pérdida de paquetes con scripts que “descartan” algunos datos.

### B. Enlace rover → orbitador → Tierra

- Usa contenedores Docker para simular módulos intermedios (ex: un microservicio por cada etapa del flujo).

---

### 🧩 3. **Procesamiento y ETL**

### A. Infraestructura simulada

- **Airflow / Prefect**: Para orquestar el pipeline ETL.
- **Spark / Pandas**: Limpieza y transformación.
- **OpenCV**: Procesamiento de imágenes (detección de rocas, segmentación).

### B. Formatos realistas

- Simular datos en formato PDS4, o convertir imágenes y telemetría a CSV, Parquet, JSON.

---

### 🗄️ 4. **Almacenamiento**

- **Raw data lake**: S3 (local o nube), MinIO.
- **Procesado**: PostgreSQL/PostGIS para datos geoespaciales.
- **Ingesta incremental**: CDC simulada con Kafka o Python scripts.

---

### 🤖 5. **Modelos de Machine Learning (opcional)**

- Clasificador de terreno marciano (modelo simple con imágenes etiquetadas).
- Predicción de fallos del sistema (modelo supervisado con datos simulados).
- Detección de anomalías (autoencoders, isolation forest).

---

### 📊 6. **Visualización**

- App web con dashboards: ya creaste una con React + Tailwind + ShadCN.
- Usa:
    - **CesiumJS** para mapa 3D de Marte
    - **Plotly/Dash** para estudiantes más científicos
    - **Grafana** si quieres integración con bases de datos de series temporales (InfluxDB)

---

## 📦 Entregables del proyecto

| Tipo | Descripción |
| --- | --- |
| ✅ App Web | Visualización interactiva del flujo de datos e imágenes |
| ✅ Repositorio GitHub | Código documentado, instructivo para reproducirlo |
| ✅ Infraestructura en Docker | Microservicios simulando cada etapa |
| ✅ Dataset sintético o real | Datos de sensores, imágenes, logs |
| ✅ Documentación pedagógica | Para enseñar flujo ETL, procesamiento, ML |
| ✅ Demo video / pitch | Corto de 2-3 minutos explicando el sistema (para reclutadores/agencias) |

---

## 🎯 Cómo captar la atención

### Para reclutadores:

- Publica en LinkedIn mostrando el stack usado, retos técnicos y la demo web.
- Muestra impacto educativo y visión futura (cómo escalarlo a otras misiones o áreas).

### Para agencias espaciales:

- Utiliza términos técnicos usados por NASA/ESA (PDS4, CCSDS, DSN).
- Propón cómo se puede adaptar para futuros rovers, estaciones lunares o investigación científica.
- Presenta el proyecto como *proof of concept* para formación de talento en misiones remotas.

---

## 🧠 Recursos para inspirarte

- NASA APIs: https://api.nasa.gov
- NASA’s Mars Open Data: https://mars.nasa.gov/msl/multimedia/raw-images/
- ESA Open Data Portal: https://www.cosmos.esa.int/web/psa
- CesiumJS + Mars tiles: https://sandcastle.cesium.com/