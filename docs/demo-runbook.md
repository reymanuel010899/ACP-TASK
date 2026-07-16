# AgentTrust — Runbook de la demo de dos agentes (U7)

> **AgentTrust** es un nombre placeholder provisional (R10).

Esta demo levanta cuatro procesos **independientes** — servicio de
verificación, registro, agente proveedor y agente solicitante — y ejecuta el
ciclo completo de confianza de extremo a extremo: descubrimiento por
capacidad → negociación → ejecución → verificación independiente →
actualización de reputación. El solicitante y el proveedor **no comparten
código** más allá del spec publicado (RFC-0001, RFC-0002) y los esquemas.

La versión automatizada de este runbook es `tests/e2e/test_two_agent_demo.py`;
esta página es el equivalente manual.

## Requisitos

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Topología

```
solicitante ──/search──▶ registro ──/reputation──▶ verificación
     │                      ▲                          ▲
     │ message/send         │ /register                │ /evidence
     ▼                      │                          │
  proveedor ────────────────┘──────────────────────────┘
```

## Pasos

Usá **cuatro terminales** (todas con el venv activado). Los puertos abajo son
ejemplos; cualquiera libre sirve.

### 1. Servicio de verificación (puerto 8080)

```bash
python -m services.verification.app --port 8080
```

Valida la Evidence contra su esquema y contra expectativas de la tarea, emite
Verification Results y acumula Reputation Records por Principal + capacidad.
La reputación **nunca** sube sin una verificación `verified` (R4).

### 2. Registro de referencia (puerto 8090)

```bash
python -m registry.app --port 8090 --verification-url http://127.0.0.1:8080
```

Indexa Agent Cards por capacidad y resuelve reputación pidiéndosela al
servicio de verificación por HTTP. Es **federable**: cualquiera puede correr
otro registro que hable este mismo contrato (R5).

### 3. Emitir una API-key de invitación (fricción anti-Sybil, KTD8)

```bash
curl -s -X POST http://127.0.0.1:8090/admin/api-keys
# => {"api_key": "<KEY>"}
```

Sin una API-key emitida por el registro, `POST /register` devuelve 403.

### 4. Agente proveedor (puerto 8100)

```bash
python -m agents.provider.agent \
  --port 8100 \
  --verification-url http://127.0.0.1:8080 \
  --registry-url http://127.0.0.1:8090 \
  --api-key <KEY>
```

Genera su par ed25519 localmente (git-ignorado, KTD8), publica su Agent Card
en `/.well-known/agent-card.json` declarando la skill `terraform.generate` y
la extensión de confianza, y se registra al arrancar.

### 5. Agente solicitante (proceso de una sola pasada)

```bash
python -m agents.requester.agent --registry-url http://127.0.0.1:8090
```

Busca en el registro, elige candidato por reputación, negocia la tarea en una
sola ronda (`task.request` → `task.offer` → `task.accept`, KTD6) y trata la
tarea como **genuinamente completa solo si la verificación independiente dice
`verified`** (R4). Imprime el resultado como JSON y sale con código `0` solo
si el resultado fue verificado.

Salida esperada (recortada):

```json
{
  "status": "verified",
  "verified": true,
  "evidence_status": "verified",
  "verification_result": { "verdict": "verified", ... },
  "artifacts": { "main.tf": "..." }
}
```

Opciones útiles: `--min-reputation 0.9` (solo proveedores probados),
`--containers N`, `--load-balancer alb`.

## Verificar la reputación actualizada

Tras una tarea verificada, el proveedor aparece por encima del umbral:

```bash
curl -s "http://127.0.0.1:8090/search?capability=terraform.generate&min_reputation=0.9"
```

El `reputation_summary` del candidato muestra `tasks_verified >= 1` y
`verification_rate: 1.0`.

## Estados del resultado del solicitante

| `status`               | Significado                                                        |
|------------------------|--------------------------------------------------------------------|
| `verified`             | COMPLETED en A2A **y** verificado de forma independiente. Confiable.|
| `rejected`             | La verificación rechazó la evidencia. **No** completo; distinto de `provider_error`. |
| `unverified`           | Completo en A2A pero sin verificación (verificador caído / sin extensión). |
| `provider_error`       | El proveedor falló la tarea a nivel A2A, o es inalcanzable.         |
| `no_candidates`        | El registro no devolvió proveedores para la capacidad.             |
| `registry_unreachable` | No se pudo alcanzar el registro.                                   |

## Prueba de humo de fallo

Si el proveedor muere a mitad de flujo, el solicitante devuelve
`provider_error` en tiempo acotado en vez de colgarse (recoge el hueco de
liveness del estado RUNNING; el diseño completo de heartbeat queda diferido).
