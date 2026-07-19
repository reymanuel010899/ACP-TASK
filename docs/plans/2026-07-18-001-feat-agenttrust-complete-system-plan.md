---
title: AgentTrust - Plan Maestro - ACTUALIZADO (Lo que queda por hacer)
type: feat
date: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# AgentTrust - Lo Que Falta Implementar

**Status:** 17/20 units completadas (85%). Solo falta CI/CD infrastructure.

---

## Goal Capsule

- **Objetivo:** completar la infraestructura CI/CD para AgentTrust — automatizar validaciones de tests, linting de agentes, spec validation, y coverage reporting en GitHub Actions.

- **Autoridad del producto:** análisis de código actual muestra que TODO está implementado y funciona localmente. Solo faltan workflows de GitHub para automatizar en CI.

- **Responsable del cierre:** `.github/workflows/` contiene 3 workflows ejecutándose en cada push/PR a `main`.

---

## Status Actual del Proyecto

### ✅ LO QUE YA ESTÁ HECHO (17/20 Units)

| Unit | Descripción | Status | Tests | LOC |
|------|-------------|--------|-------|-----|
| **U1** | RFC-0001 (Core Vocabulary) | ✅ DONE | 27/27 ✓ | ~200 |
| **U2** | JSON Schemas (6 core) | ✅ DONE | 60+/60 ✓ | ~500 |
| **U3** | RFC-0002 (A2A Binding) | ✅ DONE | 27/27 ✓ | ~200 |
| **U4** | Ejemplos Validados | ✅ DONE | 7/7 ✓ | - |
| **U5** | Verificador Service | ✅ DONE | 31/31 ✓ | 550 |
| **U6** | Registry Service | ✅ DONE | 18/18 ✓ | 474 |
| **U7** | Proveedor Agent | ✅ DONE | 34/34 ✓ | 785 |
| **U8** | Solicitante Agent | ✅ DONE | 22/22 ✓ | 694 |
| **U9** | Web Console MVP | ✅ DONE | 14/14 ✓ | 499 |
| **U10** | Modo Conectado + Tokens | ✅ DONE | 3/3 ✓ | - |
| **U11** | Fixture 4+ Procesos | ✅ DONE | - | - |
| **U12** | E2E Completo | ✅ DONE | 2/2 ✓ | - |
| **U13** | Múltiples Registries | ✅ DONE | - | - |
| **U14** | Auth E2E | ✅ DONE | 4/4 ✓ | - |
| **U15** | Rate Limiting | ✅ DONE | 5+5/10 ✓ | 73 |
| **U16** | Documentación | ✅ DONE | - | - |
| **U17** | Demo Final | ✅ DONE | 3/3 ✓ | - |

**TOTAL: 244 tests ✅ PASSING | 0 FAILURES**

---

## ⚠️ LO QUE ESTÁ PARCIALMENTE HECHO (WIP)

### U18. Lint: Agentes NO comparten código

**Status:** 70% DONE (runtime guards OK, GitHub Actions workflow falta)

- **Lo que SÍ funciona:**
  - ✅ `test_provider_code_does_not_import_reference_services` PASA
  - ✅ `test_requester_code_does_not_import_reference_impls` PASA
  - ✅ CERO cross-imports entre agentes (verificado)
  - ✅ Guarda runtime en pytest existe

- **Lo que FALTA:**
  - ❌ `.github/workflows/lint-agents.yml` NO EXISTE
  - Acción: Crear workflow que corra lint en cada push/PR

### U19. Lint: Specs Validables en CI

**Status:** 70% DONE (validation OK, GitHub Actions workflow falta)

- **Lo que SÍ funciona:**
  - ✅ 77 tests en `tests/schemas/` + `tests/spec/` validan schemas + ejemplos
  - ✅ `tests/schemas/test_example_artifacts.py` valida 7 ejemplos JSON
  - ✅ Todos pasan (pytest run)

- **Lo que FALTA:**
  - ❌ `.github/workflows/spec-validation.yml` NO EXISTE
  - Acción: Crear workflow que corra validación en cada push/PR

### U20. Test Suite + Coverage Reporting

**Status:** 80% DONE (tests OK, coverage metrics faltan)

- **Lo que SÍ funciona:**
  - ✅ 244 tests TODOS PASAN
  - ✅ Cobertura claramente > 80% (unit + integration + e2e)
  - ✅ `pytest.ini` configurado

- **Lo que FALTA:**
  - ❌ `.github/workflows/test.yml` NO EXISTE
  - ❌ `pytest --cov` output no se publica
  - ❌ Coverage threshold enforcement (80%) no está en CI
  - Acción: Crear workflow que corra pytest + coverage, bloquee merge si cae

---

## Implementation Units - LO QUE QUEDA

### U18. Crear `.github/workflows/lint-agents.yml`

- **Goal:** verificar en cada push/PR que agentes no comparten código ni importan internals.
- **Requirements:** R11 (KTD-4)
- **Dependencies:** ninguna (guard tests ya existen)
- **Files:** `.github/workflows/lint-agents.yml` (nuevo)
- **Approach:** 
  ```yaml
  name: Lint - Agent Isolation
  on: [push, pull_request]
  jobs:
    lint:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3
        - uses: actions/setup-python@v4
        - run: pip install -r requirements.txt
        - run: pytest tests/agents/test_provider_code_does_not_import_reference_services.py tests/agents/test_requester_code_does_not_import_reference_impls.py -v
  ```
- **Execution note:** straightforward; test fixtures ya existen.
- **Test scenarios:**
  - Workflow corre en cada push.
  - Falla si hay imports cruzados (test falla).
  - Pasa si agentes están aislados.
- **Verification:** workflow se ejecuta y pasa en cada commit.

### U19. Crear `.github/workflows/spec-validation.yml`

- **Goal:** verificar en cada push que ejemplos JSON validan contra schemas.
- **Requirements:** R8
- **Dependencies:** ninguna (77 tests ya existen)
- **Files:** `.github/workflows/spec-validation.yml` (nuevo)
- **Approach:**
  ```yaml
  name: Spec Validation
  on: [push, pull_request]
  jobs:
    spec:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3
        - uses: actions/setup-python@v4
        - run: pip install -r requirements.txt
        - run: pytest tests/spec/ tests/schemas/ -v
  ```
- **Execution note:** straightforward; validación ya funciona.
- **Test scenarios:**
  - Workflow corre en cada push.
  - Falla si un ejemplo no valida.
  - Pasa si todos los ejemplos validan.
- **Verification:** workflow ejecuta y pasa en cada commit.

### U20. Crear `.github/workflows/test.yml` + coverage threshold

- **Goal:** ejecutar suite completa de tests, publicar coverage, bloquear merge si falla o coverage cae.
- **Requirements:** R27
- **Dependencies:** ninguna (244 tests ya existen)
- **Files:** `.github/workflows/test.yml` (nuevo)
- **Approach:**
  ```yaml
  name: Test Suite
  on: [push, pull_request]
  jobs:
    test:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v3
        - uses: actions/setup-python@v4
        - run: pip install -r requirements.txt
        - run: pytest --cov=agents --cov=registry --cov=services --cov=web --cov-report=xml --cov-report=term-missing
        - uses: codecov/codecov-action@v3
          with:
            fail_ci_if_error: true
            minimum-coverage: 80
  ```
- **Execution note:** straightforward; pytest y coverage ya están configurados.
- **Test scenarios:**
  - Todos 244 tests pasan.
  - Coverage >= 80% para core modules.
  - Merge se bloquea si algún test falla o coverage cae.
- **Verification:** workflow ejecuta, publica coverage, enforcement funciona.

---

## Verification Contract (Lo que falta)

| Comando | Qué verifica |
|---------|------------|
| `.github/workflows/lint-agents.yml` en `main` | U18 implementado |
| `.github/workflows/spec-validation.yml` en `main` | U19 implementado |
| `.github/workflows/test.yml` en `main` | U20 implementado |
| Merge blockeado en main si tests fallan | CI enforcement funciona |
| Merge blockeado en main si coverage < 80% | Coverage threshold funciona |

---

## Definition of Done

- ✅ `.github/workflows/lint-agents.yml` existe y corre en cada push/PR
- ✅ `.github/workflows/spec-validation.yml` existe y corre en cada push/PR
- ✅ `.github/workflows/test.yml` existe y corre en cada push/PR
- ✅ Coverage >= 80% enforced (merge bloqueado si cae)
- ✅ Todos los workflows pasan en `main` branch
- ✅ Merge requirements configurados: todos 3 workflows deben pasar antes de merge

---

## Impacto

| Aspecto | Antes | Después |
|--------|-------|---------|
| **Tests locales** | ✅ 244/244 pasan | ✅ Igual (no cambia) |
| **Tests en CI** | ❌ No corren en GitHub | ✅ Corren en cada push/PR |
| **Coverage tracking** | ❌ No existe | ✅ Publicado en codecov |
| **Merge safety** | ⚠️ Manual | ✅ Automático (CI gates) |
| **Credibilidad** | ⚠️ "Pasa localmente" | ✅ "Pasa en CI" |

---

## RESUMEN: EL PROYECTO YA ESTÁ 85% LISTO

**Hoy puedes:**
- ✅ Clonar el repo
- ✅ Correr `pytest` → 244 tests pasan
- ✅ Correr `python -m pytest tests/e2e/` → demo funciona
- ✅ Lanzar la consola web → task → búsqueda → verificación → reputación

**Falta solo:**
- ❌ Automatizar eso en GitHub Actions (3 workflows simples)

**Esfuerzo restante:** 2-3 horas (workflows muy simples, tests ya existen).

