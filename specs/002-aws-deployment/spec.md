# Especificación de Feature: Despliegue Híbrido en AWS con Datos Reales de Mastcam-Z

**Feature Branch**: `002-aws-deployment`

**Creado**: 2026-10-05

**Estado**: Borrador

**Versión**: 0.1.0

**Constitución aplicada**: v1.0.0

---

## Escenarios de Usuario y Prueba *(obligatorio)*

### Escenario 1 — Despliegue acotado en AWS con control de costo (Prioridad: P1)

El equipo puede levantar una porción representativa del pipeline en AWS, ejecutar
una corrida completa, capturar evidencia de costo y de funcionamiento, y luego
destruir todos los recursos de pago, sin dejar gasto residual.

**Por qué esta prioridad**: Es la condición para cualquier afirmación de "despliegue
en la nube". Sin evidencia real, la variante AWS del repositorio sigue siendo
código sin ejecutar.

**Prueba independiente**: Aplicar el plan de Terraform previamente revisado, correr
una vez el pipeline, exportar la facturación del periodo y ejecutar la destrucción;
verificar que no quedan recursos de pago activos.

**Escenarios de aceptación**:

1. **Dado** que las alertas de presupuesto (50/80/100%) están activas,
   **Cuando** se intenta aplicar la infraestructura,
   **Entonces** el presupuesto ya existe antes que cualquier recurso de pago.

2. **Dado** un plan de Terraform generado y revisado,
   **Cuando** se aplica,
   **Entonces** se crean únicamente los recursos listados en el plan revisado.

3. **Dado** que la corrida de demostración terminó,
   **Cuando** se destruye la infraestructura,
   **Entonces** no quedan recursos de pago activos y se verifica con un listado de recursos.

---

### Escenario 2 — Ingesta de productos reales PDS4 como origen Bronze (Prioridad: P1)

El equipo puede tomar productos reales de Mastcam-Z publicados en el archivo público
PDS (ASU), conservarlos sin modificación en la capa Raw, y catalogarlos en Bronze
con su identificador original. El simulador queda limitado al tramo de transporte
(CCSDS/DSN), y ese tramo se etiqueta como simulado en cada registro.

**Por qué esta prioridad**: Es lo que hace el proyecto fiel al dominio real
(Principio I). Cambia el origen de los datos de "generados" a "observados", que es
la diferencia que un reclutador técnico va a evaluar.

**Prueba independiente**: Descargar un subconjunto acotado de productos del archivo
PDS, ejecutar la ingesta dos veces y verificar que los registros Bronze coinciden
con los productos originales, sin duplicados.

**Escenarios de aceptación**:

1. **Dado** un producto PDS4 real de Mastcam-Z,
   **Cuando** se ejecuta la ingesta,
   **Entonces** el objeto aparece en Raw sin modificación, con su checksum verificado, y
   su registro Bronze conserva el identificador PDS4 original.

2. **Dado** un producto cuyo checksum no coincide con el publicado,
   **Cuando** se valida,
   **Entonces** el producto se pone en cuarentena y no pasa a Silver.

3. **Dado** que la misma ingesta se ejecuta por segunda vez,
   **Cuando** los productos ya existen,
   **Entonces** Raw no se sobrescribe y Bronze no genera duplicados.

4. **Dado** un registro originado en el simulador de transporte,
   **Cuando** se consulta en Bronze o en el dashboard,
   **Entonces** se muestra con la marca de origen "simulado".

---

### Escenario 3 — Cobertura por sol con PySpark, comparada contra SQL (Prioridad: P2)

El equipo puede calcular la cobertura de imágenes por sol con un job PySpark sobre
Bronze/Silver, y comparar su resultado con la vista SQL existente
(`science.sol_filter_coverage`) para el mismo conjunto de entrada. La decisión de usar
Spark queda justificada por el volumen real procesado y registrada como ADR.

**Por qué esta prioridad**: Responde a una expectativa real del mercado (Spark en el
stack) y produce una comparación verificable, no una afirmación sin datos.

**Prueba independiente**: Ejecutar el job y la vista SQL sobre el mismo subconjunto y
comparar fila por fila.

**Escenarios de aceptación**:

1. **Dado** el mismo conjunto de entrada,
   **Cuando** se ejecutan el job PySpark y la vista SQL,
   **Entonces** ambos producen la misma tabla de cobertura por sol.

2. **Dado** que se midió el tiempo y el costo de ambos caminos,
   **Cuando** se redacta el ADR,
   **Entonces** el ADR registra si Spark se justifica para el volumen usado o no.

---

### Escenario 4 — Visibilidad y alertas (Prioridad: P3)

El equipo puede ver el dashboard publicado en modo solo lectura, y recibir una alerta
cuando una lectura cruza un umbral de anomalía.

**Por qué esta prioridad**: Completa el recorrido de punta a punta, pero no cambia la
validez técnica de los escenarios P1 y P2.

**Prueba independiente**: Forzar una lectura fuera de umbral y verificar que llega la
alerta y que el dashboard publicado es accesible sin credenciales de escritura.

**Escenarios de aceptación**:

1. **Dado** una lectura fuera de umbral,
   **Cuando** se procesa,
   **Entonces** se envía una alerta al destinatario configurado.

2. **Dado** el dashboard publicado,
   **Cuando** un visitante lo abre,
   **Entonces** puede verlo sin poder modificar datos ni configuración.

---

### Casos Límite

- ¿Qué pasa si el archivo PDS no está disponible durante la ingesta? La ingesta
  se reintenta sin duplicar y sin marcar como fallido lo ya persistido.
- ¿Qué pasa si un producto real no tiene etiqueta PDS4 legible? Se pone en
  cuarentena con motivo explícito, igual que un checksum inválido.
- ¿Qué pasa si la etiqueta PDS4 no publica un checksum de contenido? (Es el caso real
  del bundle usado en esta feature — ver `research.md`.) Se valida en su lugar la
  integridad de transporte (bytes recibidos vs. `Content-Length`); si no coincide,
  se pone en cuarentena igual que un checksum inválido.
- ¿Qué pasa si el costo acumulado se acerca al 80% del tope? Se dispara la alerta
  y la corrida de demostración se detiene antes de crear recursos adicionales.
- ¿Qué pasa si la destrucción falla a mitad de camino? Se reintenta; el procedimiento
  no da por cerrado el despliegue hasta verificar que no quedan recursos de pago.
- ¿Qué pasa si se ejecuta el job Spark dos veces sobre el mismo sol? El resultado es
  idéntico y no se duplican filas (idempotencia).

---

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE tener activas las alertas de presupuesto (50%, 80%, 100%)
  antes de crear cualquier recurso de pago.
- **FR-002**: Ningún recurso de pago se aplica sin que el plan de infraestructura haya
  sido revisado previamente.
- **FR-003**: Los productos reales se conservan en la capa Raw sin modificación, con su
  identificador PDS4 original y su integridad verificada: contra el checksum de
  contenido de la etiqueta PDS4 cuando el producto lo publica, o — si no lo publica,
  que es el caso real del bundle `mastcamz_ops_raw` verificado en esta feature (ver
  `research.md`, Decisión 2) — contra la integridad de transporte (bytes recibidos
  vs. `Content-Length` anunciado).
- **FR-004**: Los productos que no pasan la validación de integridad (checksum de
  contenido o, en su defecto, de transporte) o de etiqueta DEBEN quedar en cuarentena
  con motivo explícito y no avanzar a Silver.
- **FR-005**: Cada registro de origen simulado DEBE estar marcado como "simulado" en
  Bronze y en cualquier vista que lo consuma.
- **FR-006**: Ninguna credencial de AWS o de la fuente de datos aparece en código ni en
  archivos versionados; los valores se leen desde el almacén de parámetros del entorno.
- **FR-007**: La ingesta repetida del mismo conjunto de productos NO DEBE duplicar
  registros ni sobrescribir Raw.
- **FR-008**: El job PySpark DEBE producir la misma tabla de cobertura por sol que la vista
  SQL para el mismo conjunto de entrada.
- **FR-009**: El despliegue DEBE generar evidencia: exportación de facturación del
  periodo y registro de una corrida completa del pipeline.
- **FR-010**: El procedimiento de destrucción DEBE verificar que no quedan recursos de
  pago activos.
- **FR-011**: Las decisiones de fuente de datos reales, de uso de Spark y de la estrategia de
  despliegue DEBEN registrarse como ADR en `docs/ANALISIS_MODERN_DATA_STACK.md`.

### Entidades Clave

- **Producto PDS4 real**: Archivo de imagen de Mastcam-Z publicado en el archivo público,
  con identificador original, etiqueta y checksum publicado.
- **Registro de origen**: Dato con marca de origen (real o simulado) que identifica de
  dónde viene cada registro en Bronze.
- **Presupuesto de despliegue**: Tope de gasto mensual y umbrales de alerta asociados.
- **Evidencia de despliegue**: Conjunto de artefactos que prueban costo y funcionamiento
  (exportación de facturación, registro de corrida, listado de destrucción).

---

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Las alertas de presupuesto están activas antes del primer recurso de pago,
  verificable por el orden de creación.
- **SC-002**: El 100% de los productos reales ingeridos conserva su identificador PDS4
  original y pasa la verificación de integridad aplicable (checksum de contenido si la
  etiqueta lo publica; integridad de transporte si no — ver FR-003 y `research.md`).
- **SC-003**: Una segunda ejecución de la ingesta sobre el mismo conjunto produce 0
  registros duplicados.
- **SC-004**: La tabla de cobertura por sol producida por el job coincide con la vista SQL
  en el 100% de las filas del conjunto de prueba.
- **SC-005**: El costo total del despliegue de demostración queda dentro del tope definido
  en el presupuesto.
- **SC-006**: Tras la destrucción, el listado de recursos de pago activos está vacío.
- **SC-007**: El repositorio contiene la evidencia de costo y la corrida completa,
  referenciadas desde la documentación del despliegue.

---

## Suposiciones

- **Fuente de datos reales**: Se usa un subconjunto acotado de productos Mastcam-Z del
  archivo público PDS (ASU). El volumen exacto se define en el plan y se documenta en el ADR.
- **Telemetría en tiempo real**: No se asume acceso a telemetría DSN en vivo, porque no es
  pública. La clave `NASA_API_KEY` ya configurada no es requisito de esta feature.
- **Spark en AWS Glue**: El job PySpark se ejecuta en AWS Glue, porque `infra/aws/glue_athena.tf`
  ya existe y evita administrar un clúster. Se evalúa costo frente a alternativas en el ADR.
- **Ventana corta de despliegue**: La infraestructura se levanta solo para la demostración y se
  destruye al final, para respetar el crédito de estudiante.
- **Simulador acotado**: El simulador CCSDS/DSN se mantiene solo para el tramo de transporte y
  queda etiquetado como simulado.
- **Ejecución manual de Terraform**: `terraform apply` nunca corre automáticamente; siempre se
  revisa el plan antes (alineado con `infra/aws/README.md`).
- **Idioma**: La documentación nueva se redacta en español, según la constitución.

---

## Alineación Constitucional (Constitución v1.0.0)

| Principio | Cómo lo cumple esta spec |
| :--- | :--- |
| I. Fidelidad de dominio | Los datos de origen son productos reales del archivo PDS; lo simulado queda marcado (FR-003, FR-005). |
| II. Contrato Medallion | Raw inmutable (FR-003, FR-007); cuarentena antes de Silver (FR-004). |
| III. Determinismo, idempotencia, parametrización | Ingesta repetida sin duplicados (FR-007, SC-003); umbrales y credenciales parametrizados (FR-006). |
| IV. Verificación real | Pruebas de checksum, idempotencia y comparación PySpark/SQL en el plan (SC-002, SC-003, SC-004). |
| V. Seguridad de secretos | Sin credenciales en código; lectura desde el almacén de parámetros (FR-006). |
| VI. Costo en la nube | Alertas antes de recursos de pago (FR-001), plan revisado (FR-002), teardown verificado (FR-010, SC-006). |
| VII. ADR | Decisiones de fuente, Spark y despliegue registradas como ADR (FR-011). |
| VIII. Transformación declarativa y CI | Agregados Gold siguen como modelo dbt; los workflows de CI deben seguir en verde. |

---

## Clarificaciones

No quedan marcadores `[NEEDS CLARIFICATION]`. Las decisiones de alcance que podían
requerir confirmación se resolvieron con los defaults documentados en *Suposiciones*
(subconjunto acotado de productos, Spark en Glue, ventana corta con teardown).
