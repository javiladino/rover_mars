# Despliegue en mini PC — De cero a `rover_mars` corriendo

> Guía operativa para reinstalar Linux desde cero en un mini PC y desplegar
> ahí el proyecto completo. No es una guía de arquitectura (para eso está
> `docs/ANALISIS_MODERN_DATA_STACK.md`) ni de cómo se construyó el proyecto
> (`docs/GUIA_IMPLEMENTACION_MODERN_DATA_STACK.md`) — es el runbook de "tengo
> una máquina física en blanco, quiero `docker compose ps` mostrando todo en
> verde al final".

**Decisiones ya tomadas** (confirmadas antes de escribir esta guía):
- Reinstalación completa del sistema operativo (no se reaprovecha lo que
  tenga instalado hoy).
- Ubuntu Server 24.04/26.04 LTS (la LTS vigente al momento de descargar —
  sin interfaz gráfica).
- 8 GB de RAM → el stack completo entra, pero ajustado; esta guía incluye los
  ajustes necesarios (Paso 7).
- Acceso por SSH solo dentro de tu red local (LAN) — sin VPN ni exposición
  pública. Si más adelante querés acceso remoto desde fuera de casa o
  exponerlo públicamente para un reclutador, la Opción A completa de
  `docs/ANALISIS_MODERN_DATA_STACK.md` (sección 8) describe el camino con
  Tailscale + Nginx Proxy Manager — no hace falta decidirlo ahora.

No tengo acceso físico ni remoto a tu mini PC desde esta sesión: todos los
comandos de abajo los corrés vos. Si en algún paso el resultado no es el
esperado, pegame la salida y seguimos desde ahí.

---

## Paso 0 — Antes de tocar el mini PC: asegurar el código

Esto se hace **en tu Mac**, no en el mini PC, y es el paso que más fácil se
salta y más dolor causa si se salta.

### 0.1 — Confirmar que no hay nada importante en el mini PC

Vas a borrar el disco entero. Si hay algo en esa máquina que no esté
respaldado en otro lado (otra copia, la nube, lo que sea), sacalo antes de
seguir. Si ya confirmaste que no hay nada que perder, seguí.

### 0.2 — Subir tu trabajo a GitHub

En tu Mac, dentro de la carpeta del proyecto:

```bash
cd "/Users/javierladino/Documents/Javier/Portfolio/Data Engineer/rover_mars"
git status                      # debería decir "nothing to commit, working tree clean"
git log origin/main..HEAD --oneline   # lista los commits que tenés local y GitHub no tiene
```

Ahora mismo esto te va a mostrar 6 commits locales que `origin/main` no
tiene — incluyen todo el trabajo de Speckit, el pipeline MEDA completo y la
documentación que armamos. Subilos:

```bash
git push origin main
```

Si te pide autenticación y usás SSH con GitHub, debería andar directo (el
remoto ya está configurado como `git@github.com:javiladino/rover_mars.git`).
Si falla por permisos, decime el error exacto antes de continuar.

**No sigas al Paso 1 hasta que `git log origin/main..HEAD` no muestre nada.**

---

## Paso 1 — Crear el USB de instalación de Ubuntu Server

1. Descargá la ISO de **Ubuntu Server LTS** desde
   `ubuntu.com/download/server` (elegí la versión LTS más reciente que
   figure ahí — es la que trae 5 años de soporte).
2. Descargá **balenaEtcher** (`
`) para tu Mac — es la forma
   más simple y segura de crear el USB booteable sin riesgo de escribir al
   disco equivocado.
3. Metés un USB de al menos 4 GB (se borra todo su contenido), abrís
   Etcher, seleccionás la ISO descargada, seleccionás el USB, y le das
   "Flash". Tarda unos minutos.

*(Alternativa por línea de comandos con `dd` si preferís no instalar
Etcher: identificá el disco correcto con `diskutil list`, desmontalo con
`diskutil unmountDisk /dev/diskN`, y escribí con `sudo dd if=ubuntu-server.iso
of=/dev/rdiskN bs=4m status=progress`. Usá `/dev/rdiskN`, no `/dev/diskN` —
el dispositivo "raw" es mucho más rápido. Si no estás 100% seguro de cuál es
el disco correcto, usá Etcher — con `dd` un typo en el número de disco puede
borrar el disco equivocado.)*

---

## Paso 2 — Instalar Ubuntu Server en el mini PC

1. Conectá el mini PC a un monitor y teclado (solo para esta parte —
   después todo es por SSH), metele el USB, y arrancalo. Puede que tengas
   que entrar a la BIOS/UEFI (generalmente `F2`, `F7`, `F12` o `Del` al
   prender, depende de la marca) para elegir arrancar desde USB.
2. El instalador de Ubuntu Server te va a preguntar, en orden:
   - **Idioma y teclado** — lo que prefieras.
   - **Tipo de instalación** — "Ubuntu Server" (no "minimized", que es muy
     recortado; la versión normal de server ya es headless/sin GUI).
   - **Red** — si tu mini PC tiene cable ethernet, debería configurarse solo
     por DHCP. Anotá la IP que te muestre en pantalla, la vas a necesitar.
   - **Proxy / espejo de paquetes** — dejalo por defecto.
   - **Particionado de disco** — elegí "Use an entire disk" con LVM
     (la opción guiada por defecto). **Esto borra todo el disco actual** —
     es exactamente lo que querés.
   - **Perfil de usuario** — elegí un nombre de usuario y contraseña fuertes;
     vas a usarlos para el primer login SSH.
   - **OpenSSH Server** — ⚠️ **marcá esta casilla** ("Install OpenSSH
     server"). Sin esto no vas a poder entrar por SSH después y vas a tener
     que reinstalar o conectar monitor/teclado de nuevo.
   - **Snaps destacados** — no marques ninguno, los instalás después si
     hacen falta (ninguno de la lista por defecto lo es para este proyecto).
3. Cuando termine, te va a pedir reiniciar y sacar el USB. Hacelo.
4. Al reiniciar, el mini PC ya queda disponible por SSH en la IP que
   anotaste. Desconectá el monitor/teclado si querés — de acá en adelante
   todo es remoto.

---

## Paso 3 — Primer acceso por SSH desde tu Mac

```bash
ssh tu_usuario@192.168.X.X     # la IP que anotaste en el Paso 2
```

Si tu router te permite reservar esa IP para la MAC address del mini PC
(reserva DHCP), hacelo ahora — así la IP no cambia con el tiempo y no tenés
que volver a buscarla. Se configura desde la interfaz de administración de
tu router, no desde el mini PC; el menú exacto varía según la marca.

Una vez adentro:

```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

Esperá unos segundos y volvé a conectarte por SSH.

---

## Paso 4 — Hardening mínimo

No hace falta nada elaborado para un acceso solo-LAN, pero sí lo básico:

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

**Nota importante:** Docker manipula `iptables` directamente y por defecto
**ignora las reglas de `ufw`** para los puertos que publican los
contenedores (los `8080:8080`, `3001:3000`, etc. de `docker-compose.yml`).
Es decir: aunque `ufw` esté activo, cualquier dispositivo en tu LAN va a
poder llegar a Airflow/Grafana/MinIO igual, porque esos puertos no pasan por
`ufw`. Para vos esto no es un problema ahora mismo (elegiste acceso
solo-LAN y confiás en tu red doméstica), pero es bueno saberlo: si algún día
este mini PC se conecta a una red que no controlás, esos puertos quedan
expuestos ahí también. Lo dejamos documentado; si en el futuro querés
restringir esto de verdad, la herramienta que lo resuelve se llama
`ufw-docker` — no hace falta ahora.

---

## Paso 5 — Instalar Docker Engine + Docker Compose

Usamos el repositorio oficial de Docker (no el paquete `docker.io` de Ubuntu,
que suele quedar desactualizado):

```bash
# Dependencias y clave GPG oficial de Docker
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Repositorio
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Para no tener que usar sudo en cada comando docker
sudo usermod -aG docker $USER
```

Cerrá la sesión SSH y volvé a entrar (el cambio de grupo no aplica hasta
reconectar):

```bash
exit
ssh tu_usuario@192.168.X.X
docker run hello-world    # si esto corre sin "permission denied", quedó bien
docker compose version
```

---

## Paso 6 — Clonar el proyecto y configurar secretos

```bash
sudo apt install -y git
git clone git@github.com:javiladino/rover_mars.git
# Si no configuraste una clave SSH propia en este mini PC para GitHub, usá HTTPS:
#   git clone https://github.com/javiladino/rover_mars.git
cd rover_mars
```

A partir de acá, **todos los comandos `docker compose` de esta guía se
corren parado dentro de esta carpeta** (`~/rover_mars`) — es donde vive
`docker-compose.yml`. Si en algún paso siguiente ves el error `no
configuration file provided: not found`, es señal de que te moviste de
carpeta; volvé con `cd ~/rover_mars`.

```bash
cp .env.example .env
nano .env
```

Dentro de `.env`, como mínimo tenés que reemplazar **todos** los valores que
dicen `changeme_...` por algo real (no dejes ninguno igual al ejemplo — son
las credenciales de Postgres, MinIO, Airflow, Grafana y Jupyter). Para la
clave de Airflow, generala así desde el mismo mini PC:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

(Si `python3` no tiene el paquete `cryptography` instalado, `pip3 install
cryptography` primero, o simplemente generá la clave en tu Mac y pegala acá —
es solo una string, no hace falta que se genere en la misma máquina.)

Pegá el resultado como valor de `AIRFLOW_FERNET_KEY` en el `.env`. Guardá con
`Ctrl+O`, Enter, `Ctrl+X` si estás en `nano`.

---

## Paso 7 — Preparar la máquina para 8 GB de RAM

El stack completo (Kafka, Zookeeper, Postgres, MinIO, 3 contenedores de
Airflow, Grafana, Jupyter, y los dos simuladores) pide bastante memoria. Con
8 GB entra, pero sin margen de sobra — estos tres ajustes son los que marcan
la diferencia entre que ande bien y que el kernel empiece a matar
contenedores (OOM killer). Se hacen ahora porque ya tenés el repo clonado
(Paso 6) y `docker-compose.yml` existe en tu carpeta actual.

### 7.1 — Agregar swap

Primero revisá si ya tenés swap — las versiones recientes del instalador de
Ubuntu Server (particionado guiado con LVM) crean un `/swapfile`
automáticamente durante la instalación:

```bash
free -h
```

Si la línea `Swap:` ya muestra varios GB disponibles, **no hace falta hacer
nada más acá** — saltá directo al 7.2. Si en cambio muestra `0B`, creá uno de
4 GB:

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h    # deberías ver la línea Swap con 4.0Gi
```

### 7.2 — No levantar Jupyter por defecto

Jupyter no participa de ningún pipeline (ningún DAG depende de él) — es solo
para análisis exploratorio ad-hoc. En vez de incluirlo en el `docker compose
up` de todos los días, levantalo solo cuando lo vayas a usar. El comando de
"uso normal" de acá abajo es el mismo que vas a correr en el Paso 8 para
levantar todo:

```bash
# Uso normal (sin Jupyter) — parado dentro de ~/rover_mars:
docker compose up --build -d $(docker compose config --services | grep -v '^jupyter$')

# Cuando quieras usar notebooks:
docker compose up -d jupyter
# y cuando termines:
docker compose stop jupyter
```

### 7.3 — Acotar la memoria de Kafka

La imagen de Kafka por defecto puede reservar más heap del necesario para
este volumen de datos simulados. Esto es opcional pero recomendado en 8 GB —
podés agregarlo editando `docker-compose.yml` en el servicio `kafka`:

```yaml
  kafka:
    # ... lo que ya tiene ...
    environment:
      # ... las variables que ya tiene ...
      KAFKA_HEAP_OPTS: "-Xmx512M -Xms512M"
```

No hace falta tocar nada más — si en el Paso 8 ves que todo arranca bien sin
este cambio, podés dejarlo para más adelante.

---

## Paso 8 — Levantar el stack

```bash
docker compose up --build -d $(docker compose config --services | grep -v '^jupyter$')
```

La primera vez tarda varios minutos (está construyendo las imágenes de
`rover_simulator`, `dsn_receiver` y `airflow` desde cero). Mientras tanto:

```bash
docker compose ps
```

Vas a ver cada servicio en estado `starting` y después `healthy` o
`running`. Los que terminan y se quedan como `exited (0)` a propósito son
`minio_init` y `airflow_init` — son contenedores de inicialización que
corren una vez y terminan, no es un error.

Si algo queda en `unhealthy` o reiniciando en loop, revisá sus logs:

```bash
docker compose logs -f <nombre_del_servicio>
```

### Si ves `pull access denied for minio/mc` (o `minio/minio`)

Esto ya no debería pasarte si cloná el repo después de octubre de 2026 — el
`docker-compose.yml` fue corregido —, pero si lo ves: **no es un problema de
tu conexión, tu cuenta de Docker ni un rate-limit**. Se verificó
directamente contra los registries (Docker Hub, Quay.io, y el binario
directo en `dl.min.io`) que **MinIO Inc. discontinuó la distribución
gratuita de `minio/minio` y `minio/mc`**, en cualquier tag, incluidos los que
ya estaban fijados en este proyecto. `docker login` no lo arregla — el
acceso está bloqueado para todos, no es un límite de cuenta.

El reemplazo ya aplicado en este repo usa el espejo "legacy" (congelado,
sin actualizaciones futuras, pero funcional) que mantiene Bitnami:
`bitnamilegacy/minio` y `bitnamilegacy/minio-client`. Si por algún motivo
tu copia del repo todavía tiene las imágenes viejas, actualizala con
`git pull`, o aplicá manualmente estos dos cambios en `docker-compose.yml`:

- Servicio `minio`: `image: bitnamilegacy/minio:latest`, y la ruta de datos
  cambia de `/data` a `/bitnami/minio/data` (tanto en `command:` como en el
  volumen montado).
- Servicio `minio_init`: `image: bitnamilegacy/minio-client:latest`, y las
  llamadas a `/usr/bin/mc` pasan a ser simplemente `mc` (el binario queda en
  el `PATH` de esta imagen en otra ubicación).

Bitnami advierte que este repo "legacy" podría eliminarse en el futuro — no
es una solución definitiva, es la que funciona hoy. Si en algún momento deja
de estar disponible, el camino de reemplazo sería evaluar un servidor
S3-compatible distinto (por ejemplo Garage o SeaweedFS) para el rol que hoy
cumple MinIO en local — AWS S3 real (la opción de nube, Paso "Próximos
pasos" de esta guía) no se ve afectado por nada de esto.

---

## Paso 9 — Verificar que todo funciona

Desde el navegador de tu Mac (reemplazando por la IP de tu mini PC):

| Servicio | URL | Qué revisar |
|---|---|---|
| Airflow | `http://192.168.X.X:8080` | Login con `AIRFLOW_ADMIN_USER`/`PASSWORD` de tu `.env`. Deberías ver los DAGs `mastcamz_full_pipeline` y `meda_full_pipeline`. |
| MinIO Console | `http://192.168.X.X:9001` | Login con `MINIO_ACCESS_KEY`/`SECRET_KEY`. Deberían existir los 9 buckets (`mastcamz-*` y `meda-*`). |
| Grafana | `http://192.168.X.X:3001` | Login con `GRAFANA_ADMIN_USER`/`PASSWORD`. No va a tener paneles armados todavía (ver `docs/DESCRIPCION_PROYECTO.md`, sección de estado actual) — pero debería conectar. |
| Kafka UI | `http://192.168.X.X:8085` | Deberías ver los 7 tópicos listados. |

Para probar el pipeline Mastcam-Z de punta a punta, el simulador ya está
generando datos solo (`rover_simulator` corre siempre encendido). Para
probar MEDA, seguí `specs/001-meda-pipeline/quickstart.md` — los comandos de
ahí ya están corregidos para los nombres reales de los servicios
(`rover_simulator`, `airflow_scheduler`).

---

## Si algo falla por memoria

Señales de que te quedaste corto de RAM: contenedores en `Restarting`,
`docker compose ps` mostrando salidas con código distinto de 0 en servicios
que no son `minio_init`/`airflow_init`, o el mini PC respondiendo muy lento
por SSH.

```bash
free -h                         # cuánta RAM/swap libre queda
docker stats --no-stream        # cuánta memoria usa cada contenedor ahora mismo
dmesg | grep -i "killed process"  # confirma si el kernel mató algo por falta de memoria
```

Si confirmás un OOM kill: aplicá el ajuste de Kafka del Paso 7.3 si todavía
no lo hiciste, asegurate de no tener Jupyter corriendo en simultáneo, y como
último recurso considerá no correr `kafka_ui` permanentemente (es solo una
herramienta de inspección, no lo necesita ningún pipeline) — se levanta
igual que Jupyter, solo cuando lo vayas a usar.

## Si se llena el disco (incidente real, ya corregido en el repo)

`rover_simulator` corre con `restart: unless-stopped` y, con el
`SIMULATION_INTERVAL_SEC=30` que traía el proyecto antes, generó **76GB en
`minio_data` en ~37 horas** sin supervisión — suficiente para llenar un disco
de 98GB al 100% y tumbar Kafka y el scheduler de Airflow (ambos escriben al
disco constantemente; con 0 bytes libres, mueren con código de salida
distinto de 0). El síntoma visible fue un "Internal Server Error" en Airflow,
que no tenía relación aparente con el disco hasta revisar `docker system df -v`.

**Diagnóstico** (de mayor a menor utilidad, todos de solo lectura):

```bash
df -h /                  # ¿qué % de uso tiene la partición raíz?
docker system df -v      # desglose exacto por volumen — buscá el que más pesa
docker compose ps        # ¿algún servicio en Exited con código != 0?
```

Si `minio_data` es el volumen grande (lo más probable, dado que es donde
aterrizan las imágenes Raw/Bronze/Silver/Gold que genera el simulador sin
parar), la recuperación es: parar lo que escribe/lee de MinIO, borrar el
volumen, recrearlo vacío, y volver a levantar lo que se haya caído por el
disco lleno:

```bash
docker compose stop rover_simulator dsn_receiver minio
docker volume rm rover_mars_minio_data
docker compose up -d minio
docker compose up -d minio_init          # recrea los 9 buckets en el volumen vacío
docker compose up -d kafka airflow_scheduler rover_simulator dsn_receiver
docker compose ps
```

**La causa de fondo ya está corregida en el repo** (`.env.example` y el
fallback en `docker-compose.yml` pasaron de `SIMULATION_INTERVAL_SEC=30` a
`900` — ~1.7GB/día en vez de ~2GB/hora, y de paso coincide con el cron de
`mastcamz_full_pipeline`, `*/15 * * * *`). Si clonaste el repo antes de este
cambio, actualizá tu `.env` a mano con `SIMULATION_INTERVAL_SEC=900` y
recreá el servicio: `docker compose up -d rover_simulator`.

## Si `dbt_build` falla sin mostrar ningún error (exit code 2, log vacío)

Síntoma: la tarea `dbt_build` termina en `up_for_retry` o falla, y el log de
Airflow para esa tarea no muestra absolutamente nada entre "Output:" y el
código de salida — ni un mensaje de dbt, ni un traceback. Incluso corriendo
el comando a mano con `docker compose exec`, `dbt deps` devuelve `EXIT=2`
sin imprimir una sola línea.

**Causa**: permisos. La carpeta `dbt/` del host (montada en
`/opt/airflow/dbt`) queda con dueño `1000:1000` (tu usuario de Linux), pero
el proceso de Airflow dentro del contenedor corre como `uid=50000(airflow)
gid=0(root)` — no coincide ni con el dueño ni con el grupo de esos archivos,
así que Airflow accede como "otros", y los permisos por defecto
(`rwxrwxr-x` / `rw-rw-r--`) no le dan escritura a "otros". `dbt deps`
necesita crear la carpeta `dbt_packages/` ahí mismo para instalar
`dbt_utils`, no puede, y falla tan temprano en su arranque que ni llega a
imprimir su propio error — de ahí el log vacío, que es lo más engañoso de
este incidente.

**Diagnóstico** (confirma el desajuste de usuario/dueño):

```bash
docker compose exec airflow_scheduler bash -c "whoami; id; ls -la /opt/airflow/dbt/"
```

**Fix** (en el host, no dentro del contenedor):

```bash
chmod -R o+rwX dbt/
```

Es seguro para un mini PC de un solo usuario — solo agrega escritura para
"otros" sobre esa carpeta puntual, no toca el resto del repo. Después de
esto, `dbt deps`/`dbt build` corren normal. Si en el futuro `git pull` trae
modelos `dbt/` nuevos, puede hacer falta repetir este `chmod` (los archivos
nuevos no heredan el bit de "otros" automáticamente).

## Si los umbrales `MEDA_*` en `.env` no parecen tener efecto

Las 8 variables de umbral de anomalía MEDA (`MEDA_TEMP_MIN_C`,
`MEDA_PRESSURE_MAX_HPA`, etc.) estaban documentadas en `.env.example` y las
lee `airflow/plugins/meda_anomaly_rules.py`, pero nunca estaban mapeadas en
el bloque `environment:` del servicio de Airflow en `docker-compose.yml` —
cambiarlas en `.env` no llegaba al contenedor. Ya corregido (ver el bloque
`environment:` de `x-airflow-common`). Si tu copia es anterior a este fix,
`git pull` lo trae; después alcanza con `docker compose up -d` (es una
variable de entorno, no un cambio de código — no hace falta `--build`).

## Si `validate_bronze` (pipeline MEDA) falla con log vacío

Mismo síntoma que el caso anterior — log de la tarea completamente vacío
entre "Pre task execution logs" y "Post task execution logs", sin ningún
traceback visible.

**Causa**: `airflow/dags/meda_pipeline.py` hacía
`from simulator.ccsds_encoder import crc16_ccitt` para validar el checksum
de cada paquete MEDA. El problema: `simulator/` **nunca se copia ni se
monta dentro de los contenedores de Airflow** (solo existe para el servicio
`rover_simulator` y para Jupyter) — esa importación fallaba con
`ModuleNotFoundError` en el primer paquete que procesaba la tarea, y esa
excepción puntual no quedaba capturada en el log.

**Fix** (ya aplicado en el repo): la función `crc16_ccitt` es pura y sin
dependencias, así que se movió a `common/rovermars_common/ccsds.py` — el
módulo compartido al que tanto `simulator/` como `airflow/` ya tienen
acceso por `PYTHONPATH`, en vez de hacer que un servicio dependa del código
fuente de otro. `simulator/ccsds_encoder.py` ahora reexporta desde ahí en
vez de definirla dos veces.

**Importante — `common/` no es un volumen, se copia al construir la
imagen**: a diferencia de `dbt/`, `airflow/dags` y `airflow/plugins` (que
sí son volúmenes montados en vivo), cualquier cambio en `common/` requiere
`docker compose build` para que los contenedores lo vean — un simple
`docker compose up -d` no alcanza, porque la imagen ya construida no sabe
que el archivo fuente cambió:

```bash
docker compose build
docker compose up -d
```

## Si armaste paneles en Grafana a mano y después desaparecieron

Síntoma real que pasó en este proyecto: el dashboard de Grafana quedó con el
título pero sin paneles ni queries SQL, de un día para el otro.

**Causa**: `docker-compose.yml` monta
`./config/grafana/provisioning:/etc/grafana/provisioning`, pero esa carpeta
nunca existió en el repo (ni versionada en git). Cualquier panel armado desde
la UI de Grafana se guarda únicamente en el volumen `grafana_data` (la base
SQLite interna de Grafana) — no en ningún archivo del repo. Si ese volumen se
pierde (recrear el stack, `docker compose down -v`, migrar de máquina), los
paneles se van con él y no hay forma de recuperarlos salvo rehacerlos de
memoria.

**Fix**: el dashboard de MEDA/Mastcam-Z ahora está versionado como código en
`config/grafana/provisioning/`:

- `datasources/datasource.yml` — provisiona el datasource Postgres
  automáticamente (usa las variables `POSTGRES_USER`/`POSTGRES_PASSWORD`/
  `POSTGRES_DB` que ya pasa `docker-compose.yml` al contenedor de Grafana).
- `dashboards/dashboards.yml` — le dice a Grafana que cargue dashboards desde
  esa misma carpeta.
- `dashboards/rover_telemetry.json` — los 4 paneles (temperatura/presión,
  cobertura de imágenes, viento, anomalías) con sus queries SQL reales contra
  `science.meda_silver_readings` y `science.sol_filter_coverage`.

Para que el mini PC recoja esto:

```bash
git pull
docker compose up -d grafana
```

No hace falta `--build` (son archivos montados por volumen, no copiados a la
imagen). Si ya habías creado a mano un datasource Postgres en la UI, vas a
terminar con dos — borrá el manual desde Grafana → Connections → Data
sources, y dejá el que dice "Postgres - rover_mars" (el provisionado).

**Para que esto no se repita**: cualquier cambio a los paneles debería
hacerse editando `rover_telemetry.json` (y subiendo el `version` del
dashboard, o simplemente confiando en `updateIntervalSeconds: 30` del
provider para que se re-sincronice) en vez de solo tocar la UI. Los cambios
hechos solo en la UI (`allowUiUpdates: true`) se conservan, pero vuelven a
depender del volumen `grafana_data` hasta que los bajes al JSON.

---

## Próximos pasos (opcionales, no bloquean nada de lo de arriba)

- **Acceso remoto fuera de tu LAN**: cuando quieras, Tailscale es el camino
  más simple (una VPN que no requiere abrir puertos en tu router) — ver
  `docs/ANALISIS_MODERN_DATA_STACK.md`, sección 8, Opción A.
- **Exponerlo públicamente** para que un reclutador entre sin VPN: la misma
  sección describe Nginx Proxy Manager + TLS por encima de lo que ya tenés
  corriendo acá — no hace falta rehacer nada de esta guía, se agrega encima.
- **Despliegue en AWS**: es un camino totalmente separado (no reemplaza al
  mini PC, lo complementa) — está descripto en
  `docs/DESCRIPCION_PROYECTO.md` y detallado como Terraform en `infra/aws/`.
