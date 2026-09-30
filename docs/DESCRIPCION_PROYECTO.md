# Rover Mars — Descripción General del Proyecto

> Este documento cuenta la historia completa del proyecto en lenguaje natural:
> qué es, qué problema simula, cómo están construidos y conectados sus dos
> pipelines de datos, cómo se levanta y se usa todo en una máquina local, y
> cómo está pensado el camino hacia un despliegue en AWS. Para el detalle
> técnico de cada decisión (por qué se eligió cada tecnología, qué se descartó
> y por qué) está `docs/ANALISIS_MODERN_DATA_STACK.md`; para el paso a paso de
> cómo se construyó, `docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md`; para los
> diagramas de dependencias, `docs/INFRAESTRUCTURA.md`. Aquí no se repiten esos
> detalles — se explica el conjunto.

---

## Qué es este proyecto

Rover Mars es una réplica funcional, construida desde cero, del sistema de
datos que usa la NASA para recibir información desde el rover Perseverance en
Marte, procesarla automáticamente y dejarla lista para que un científico la
use. No trabaja con un dataset descargado ni con datos de ejemplo genéricos:
genera sus propios datos simulando dos instrumentos reales de la misión Mars
2020 — la cámara Mastcam-Z y la estación ambiental MEDA —, los transmite como
si vinieran realmente desde Marte (con el mismo protocolo de empaquetado que
usa la NASA, con el mismo retraso de varios minutos que tarda la luz en
recorrer la distancia Tierra-Marte, y con los mismos formatos de producto de
datos que usa el archivo público de la misión), y luego los procesa con
exactamente el mismo tipo de arquitectura que usaría hoy un equipo de
ingeniería de datos en cualquier empresa: streaming, orquestación, capas de
calidad creciente, transformación declarativa y almacenamiento en la nube.

El resultado son dos pipelines de datos independientes pero paralelos —uno
para las imágenes de la cámara, otro para la telemetría ambiental— que
comparten toda la infraestructura de abajo (el mismo Kafka, el mismo Postgres,
el mismo Airflow, el mismo motor de transformación dbt), y que conviven en un
único `docker compose up`.

## Qué se quiere lograr

El objetivo no es simular Marte por simular Marte: es tener un proyecto de
portafolio que demuestre, con un caso de uso real y verificable, exactamente
las habilidades que hoy pide una vacante de Data Engineer — sin recurrir a un
tutorial genérico. Eso significa tres cosas al mismo tiempo:

**Fidelidad de dominio.** Cada pieza técnica responde a una fuente real y
citada, no a una simplificación inventada: el formato de paquete CCSDS
133.0-B-2, el modelo de cámara CAHVOR, el formato de producto PDS4, y las
ecuaciones de calibración de MEDA vienen de papers y estándares reales (ver
las referencias en `README.md` y en los módulos de calibración). Cuando algo
sí se simplifica —porque replicar la física exacta no aporta valor de
ingeniería de datos— se dice explícitamente en el código y en la
documentación, nunca se presenta como si fuera una réplica perfecta.

**Un stack de datos moderno de verdad, no solo en el nombre.** El proyecto
nació como una simulación de infraestructura (Kafka, Airflow, MinIO, Postgres)
y evolucionó deliberadamente para incorporar las piezas que hoy separan un
prototipo de un sistema production-grade: transformación declarativa con dbt,
tests automatizados, CI/CD con GitHub Actions, gestión de secretos fuera del
código, y un camino de despliegue en la nube razonado por costo (no solo "usar
todo lo que hay disponible").

**Que se pueda auditar y confiar en él.** El proyecto tiene una constitución
técnica (`.specify/memory/constitution.md`) que exige que todo el pipeline sea
determinista, idempotente, parametrizado y con responsabilidades separadas —y
esas cuatro propiedades no quedaron como buenas intenciones: se auditó el
código real, se encontraron bugs reales (una key de S3 que rompía la
idempotencia, una colisión de datos que perdía muestras de telemetría
silenciosamente, un commit prematuro de Kafka que podía perder mensajes ante
un fallo) y se corrigieron con tests que impiden que vuelvan a aparecer.

## Los dos pipelines de datos

### Pipeline Mastcam-Z — la cámara

Mastcam-Z es la cámara estéreo de zoom del rover: toma fotografías del terreno
marciano en 16 filtros distintos (desde azul visible hasta infrarrojo
cercano), y cada imagen sale de la cámara acompañada de su propio metadato de
misión (en qué sol —día marciano— se tomó, con qué filtro, con qué óptica).

En este proyecto, un simulador (`simulator/mastcamz_simulator.py`) genera esas
imágenes sintéticas y las empaqueta exactamente como lo haría el hardware real
del rover: las fragmenta en paquetes CCSDS, les agrega un checksum, y las
publica en Kafka como si estuviera transmitiendo por radio UHF hacia el
orbitador que las retransmite a la Tierra. Un segundo servicio
(`ingestion/dsn_receiver.py`) hace el papel de la estación terrena de la Red
del Espacio Profundo (Goldstone, Madrid o Canberra): recibe esos paquetes,
simula el retraso de varios minutos que tarda la señal en llegar desde Marte,
valida su integridad, y los deja catalogados como productos "Bronze" —
validados pero todavía sin calibrar.

De ahí en adelante toma el control un DAG de Airflow
(`airflow/dags/mastcamz_pipeline.py`) que hace lo que en la vida real hace el
laboratorio de procesamiento de imágenes de la NASA (el MIPL): corrige el
sesgo electrónico del sensor, corrige la respuesta de cada filtro, aplica el
modelo geométrico de la cámara para saber exactamente hacia dónde apuntaba
cada píxel, y dejar el resultado calibrado ("Silver") tanto en el data lake
(MinIO/S3) como indexado geoespacialmente en Postgres con PostGIS —de modo que
más adelante se pueda preguntar, por ejemplo, "qué imágenes cubren esta zona
del cráter Jezero". Finalmente agrega estadísticas por sol y arma un resumen
("Gold") listo para visualizar.

### Pipeline MEDA — la estación ambiental

MEDA (Mars Environmental Dynamics Analyzer) es el conjunto de sensores
ambientales del rover: mide temperatura del aire, presión atmosférica, viento
(velocidad y dirección), radiación ultravioleta y humedad, varias veces por
sol. A diferencia de una cámara, que produce un archivo grande de vez en
cuando, un sensor ambiental produce muchas lecturas pequeñas y continuas — un
patrón de datos completamente distinto, y por eso este pipeline se construyó
como una segunda línea independiente, no como una extensión de la de
Mastcam-Z.

Un segundo simulador (`simulator/meda_simulator.py`) genera esas lecturas con
un perfil diurno de temperatura realista y las empaqueta también como paquetes
CCSDS (con su propio rango de identificadores de instrumento), publicándolas
en un tópico de Kafka propio. El DAG de Airflow que las procesa
(`airflow/dags/meda_pipeline.py`) hace algo que el pipeline de Mastcam-Z no
necesitaba hacer con el mismo rigor: **poner en cuarentena** activamente los
paquetes que llegan corruptos o con un identificador de sensor desconocido, en
vez de simplemente descartarlos o dejarlos pasar. Cada paquete se valida por
checksum, por rango de identificador y por completitud de sus campos; el que
falla queda registrado en Postgres con la razón exacta de por qué se rechazó
(`crc_mismatch`, `unknown_apid`, `payload_too_large`, `missing_fields`), y
nunca avanza a la capa Silver. Los que sí pasan se calibran con las fórmulas
físicas reales de cada sensor (temperatura, presión, viento, UV, humedad) y se
consolidan por instante de muestreo, cruzándose además con la posición del
rover para saber dónde estaba parado cuando tomó cada lectura. Un módulo de
reglas de anomalía aparte marca automáticamente lecturas fuera de rango físico
razonable (por ejemplo, una temperatura o presión imposible, o un viento tan
fuerte que sugiere una tormenta de polvo).

### Cómo se conectan entre sí

Los dos pipelines son independientes en su lógica de negocio —tienen su propio
simulador, su propio DAG, sus propias tablas, sus propios módulos de
calibración y de reglas de anomalía—, pero **comparten toda la plataforma que
los sostiene**, y esa es una decisión deliberada, no una casualidad:

- Los dos publican y consumen del mismo clúster de Kafka, solo que en tópicos
  distintos (`mastcamz.*` para uno, `telemetry.meda.raw` para el otro).
- Los dos guardan sus objetos crudos y calibrados en el mismo MinIO/S3, en
  buckets con nombres distintos (`mastcamz-*` vs `meda-*`) pero bajo la misma
  arquitectura Bronze→Silver→Gold.
- Los dos escriben en la misma base de datos Postgres, aunque en namespaces
  separados (las tablas de Mastcam-Z viven en el schema `public`, heredado de
  cuando era el único pipeline; las de MEDA se diseñaron desde el principio en
  schemas `raw`/`science` explícitos, un poco más ordenado).
- Los dos terminan su corrida ejecutando el mismo motor de transformación
  declarativa, dbt, que construye modelos de negocio (`fct_sol_summary` para
  uno, `fct_meda_sol_summary` para el otro) sobre esas mismas tablas.
- Los dos reutilizan literalmente el mismo código para las partes que no
  tenía sentido duplicar: la construcción del cliente de MinIO/S3
  (`common/rovermars_common/storage.py`) y el mecanismo para diferir el commit
  de offsets de Kafka hasta confirmar que todo el resto del pipeline tuvo
  éxito (`airflow/plugins/kafka_offsets.py`) los usan ambos DAGs sin
  modificación. En cambio, la calibración física y las reglas de anomalía
  **no** se comparten a propósito: son dominios físicos distintos (óptica de
  cámara vs. sensores ambientales) y mezclarlos habría acoplado dos cosas que
  cambian por razones distintas.

El resultado es que, si mañana se agregara un tercer instrumento del rover
(por ejemplo, el espectrómetro SuperCam), el patrón a seguir ya está probado
dos veces: un simulador propio, un DAG propio, tablas propias, y reutilizar
—no reinventar— la mensajería, el almacenamiento y el mecanismo de
commit seguro.

## Cómo funciona todo en una máquina local

Todo el proyecto se levanta con un solo comando, `docker compose up --build
-d`, después de copiar `.env.example` a `.env` y completar las credenciales
(ninguna vive en el código ni en `docker-compose.yml`; ver la sección de
seguridad de la constitución del proyecto). Ese comando levanta trece
servicios sobre una misma red interna de Docker:

Zookeeper y Kafka forman el sistema de mensajería por el que viajan los
paquetes simulados de ambos instrumentos. Postgres, con la extensión
geoespacial PostGIS ya habilitada, es la base de datos relacional donde
aterrizan las capas Silver de los dos pipelines. MinIO se comporta como un
Amazon S3 en miniatura —mismo protocolo, mismo modelo de buckets y objetos— y
ahí viven las capas Raw, Bronze, Silver y Gold de ambos pipelines en forma de
archivos. Airflow (interfaz web, planificador y un contenedor de
inicialización) orquesta los dos DAGs con un único executor local, sin
necesitar un clúster de workers separado. Grafana queda conectado a Postgres,
listo para construir paneles sobre las vistas de telemetría ya definidas en el
esquema (aunque hoy no trae un dashboard pre-armado: eso es trabajo pendiente,
no algo ya resuelto). Jupyter monta el código y los datos para permitir
análisis exploratorio ad-hoc, sin que ninguna tarea del pipeline dependa de
él. Y finalmente los dos simuladores: `rover_simulator` corre encendido todo
el tiempo generando imágenes Mastcam-Z de forma continua, mientras que
`meda_simulator.py` vive dentro de ese mismo contenedor pero se ejecuta a
demanda (`docker compose exec rover_simulator python meda_simulator.py
...`) — no genera tráfico solo, hay que pedírselo explícitamente, lo cual
tiene sentido para un instrumento cuyo pipeline todavía se está construyendo
y probando de forma controlada, escenario por escenario (ver
`specs/001-meda-pipeline/quickstart.md`).

Una vez arriba, el ciclo de vida de un dato es siempre el mismo, sin importar
el instrumento: nace en un simulador, viaja por Kafka, un DAG de Airflow lo
recibe y lo hace pasar por validación, calibración y agregación, dbt construye
sobre el resultado los modelos analíticos, y todo queda disponible para
consultarse desde Postgres, desde el propio data lake en MinIO, o desde
Grafana. La diferencia entre correr el pipeline de Mastcam-Z (que se dispara
solo, cada 15 minutos, vía cron) y el de MEDA (que hoy se dispara a mano desde
la interfaz de Airflow o por línea de comandos) es una decisión de la etapa en
la que está cada uno, no una limitación de la plataforma.

## Qué tan cerca está de un despliegue real

Vale la pena ser honesto sobre el estado actual antes de hablar del plan de
nube: hoy todo el proyecto corre en local, sobre Docker Compose, en la máquina
de quien lo desarrolla. No hay nada desplegado en Internet todavía. Lo que sí
existe es el **plan de despliegue completo, razonado y ya escrito como
código** (Terraform), a la espera de aplicarse.

## Cómo se prevé desplegar en AWS

El plan de nube no consiste en "mover todo a servicios gestionados de AWS" —
esa sería la opción más cara y, para un proyecto de portafolio con un crédito
de estudiante limitado, la menos inteligente. En cambio, el criterio que guía
cada decisión (documentado como una serie de ADRs en
`docs/ANALISIS_MODERN_DATA_STACK.md`, secciones 6 y 11 a 20) es: **¿qué parte
del stack gana más señal técnica por cada dólar que cuesta, y qué parte es
más barata y sensata dejar autogestionada?**

Con ese criterio, el plan reparte la infraestructura en dos grupos:

Lo que se queda autogestionado en una única instancia EC2, corriendo el mismo
`docker-compose` que ya corre en local (con ajustes menores de configuración),
es Airflow y Kafka. La razón es puramente de costo: la versión gestionada de
Airflow en AWS (MWAA) empieza en el orden de 300 dólares mensuales fijos, y la
de Kafka (MSK) en el orden de 150, incluso con el clúster más pequeño posible
— cifras que agotarían un crédito de estudiante en semanas sin aportar ninguna
capacidad que el proyecto no tenga ya funcionando.

Lo que sí pasa a ser un servicio gestionado real de AWS es todo lo que tiene
un costo marginal bajo y una señal alta para quien evalúe el proyecto: el data
lake se convierte en buckets de Amazon S3 reales (el código ya está preparado
para esto — el mismo cliente de almacenamiento sirve tanto para MinIO local
como para S3 real, solo cambia una variable de entorno); la base de datos pasa
a ser una instancia de Amazon RDS con PostgreSQL, dentro del nivel gratuito de
12 meses; la capa Gold, una vez publicada como Parquet, se vuelve consultable
por SQL serverless con Glue y Athena sin tener que mantener un warehouse
propio; las alertas de anomalías (hoy solo un log) pasan a un tópico real de
SNS; los secretos se gestionan con AWS Systems Manager Parameter Store en vez
de un archivo `.env`; y la landing pública del proyecto (el dashboard
estático) se sirve desde S3 detrás de CloudFront, para que quede siempre
disponible sin depender de que la instancia EC2 esté encendida.

Toda esa infraestructura —los buckets, la base de datos, la instancia EC2, los
roles de permisos, la función Lambda que reacciona a nuevos objetos en el
lake, el catálogo de Glue, la distribución de CloudFront— ya está escrita como
código Terraform en `infra/aws/`, lista para aplicarse. Antes de aplicar nada,
el plan incluye un guardrail explícito: una alarma de AWS Budgets configurada
al 50%, 80% y 100% del límite mensual definido, para que un error de
configuración no agote el crédito sin avisar. El paso de aplicar esta
infraestructura (`terraform plan` seguido de `terraform apply`, revisando
siempre el plan antes) es intencionalmente manual y no automático: gasta
crédito real, así que nunca ocurre sin que alguien lo revise primero.

## Dónde seguir leyendo

Este documento da la vista panorámica. Para profundizar:

- **Por qué se tomó cada decisión de arquitectura**, con alternativas
  consideradas y descartadas: `docs/ANALISIS_MODERN_DATA_STACK.md`.
- **Cómo se construyó, paso a paso, fase por fase** (incluida la auditoría de
  robustez que encontró y corrigió los bugs mencionados arriba):
  `docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md`.
- **Los diagramas de qué se conecta con qué**, a nivel de servicio, de tarea
  de Airflow y de modelo de dbt: `docs/INFRAESTRUCTURA.md`.
- **Las reglas no negociables que gobiernan cualquier cambio nuevo** al
  proyecto (determinismo, idempotencia, parametrización, responsabilidad
  única, y el resto de principios): `.specify/memory/constitution.md`.
- **La especificación completa del pipeline MEDA** (requisitos, escenarios de
  aceptación, contratos de datos): `specs/001-meda-pipeline/`.
