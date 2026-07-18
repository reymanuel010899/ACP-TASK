# AgentTrust Mobile (Flutter)

Native mobile client for the **AgentTrust** A2A trust / verification /
reputation layer. Faithful to the Pencil designs, **mock-first**: the whole app
runs on an in-memory mock data layer behind clean repository interfaces, so the
real HTTP integration with the Python stack (`registry/`, `services/`,
`agents/`) drops in later without touching the UI.

> ⚠️ **Written without a local Flutter SDK.** This project was authored by hand
> and has **not been compiled or run** yet — Flutter/Dart were not installed on
> the machine where it was written. Expect to fix a small number of issues on
> first `flutter analyze`. The steps below get you from source to a running app.

---

## Prerequisites

- **Flutter 3.22+ / Dart 3.4+** (`flutter --version`). Install:
  <https://docs.flutter.dev/get-started/install>
- iOS: Xcode + a simulator. Android: Android Studio + an emulator (the SDK was
  not present on the authoring machine — install it for Android targets).

## Get it running

From `mobile/`:

```bash
# 1. Generate the platform folders (ios/, android/) into this existing project.
#    Safe: it fills in missing platform scaffolding and leaves lib/ untouched.
flutter create . --project-name agenttrust_mobile --platforms=ios,android

# 2. Fetch dependencies.
flutter pub get

# 3. Static analysis (fix anything it flags — see "Known caveats").
flutter analyze

# 4. Run the model tests.
flutter test

# 5. Launch on a simulator/emulator.
flutter run
```

There is **no code generation step** — Riverpod providers are declared manually
(no `build_runner`), so `flutter pub get` is all the wiring you need.

---

## Architecture

Feature-first with a light data/domain/presentation split. Riverpod is the DI
glue; go_router owns navigation.

```
lib/
├── main.dart                     # ProviderScope + mock repository overrides
├── app.dart                      # MaterialApp.router, dark-first Material 3
├── core/
│   ├── theme/                    # tokens, ColorScheme, AppTokens ThemeExtension
│   ├── router/app_router.dart    # go_router StatefulShellRoute (4 tabs)
│   ├── widgets/                  # AgentCard, StatCard, GlassNavBar, stepper…
│   └── format.dart               # price / rate / relative-time helpers
├── domain/models/                # Principal, Offer, ReputationRecord, Task…
│                                 #   mirror schemas/*.schema.json field names
├── data/
│   ├── repositories/             # abstract interfaces + Mock* implementations
│   ├── fixtures/demo_fixtures.dart
│   └── providers/app_providers.dart  # throw-by-default repo providers
└── features/
    ├── home/                     # dashboard + active-task banner
    ├── request/                  # Nueva Solicitud (texto/audio), chat, progreso
    ├── agents/                   # Registrar Agente, Explore
    └── profile/                  # Profile
```

### Screens (from the Pencil design)

| Screen | Route | Notes |
|---|---|---|
| Home | `/home` | Stats, agentes destacados, actividad, CTA, banner de tarea activa |
| Nueva Solicitud (texto) | `/request` | Capacidad, descripción, presupuesto, rep. mínima, fan-out, chat |
| Nueva Solicitud (audio) | `/request` (toggle) | Grabación UI-only (waveform + timer), rellena descripción |
| Ofertas + Progreso | `/task/:id` | Ofertas ordenadas por precio, seleccionar, stepper, verificada |
| Registrar Agente | `/register` | Endpoint, clave ed25519, capacidades, bearer, precio público/mínimo privado |
| Explore | `/explore` | Búsqueda del registry (sin diseño Pencil, on-brand) |
| Profile | `/profile` | Principal, claves, stats, capacidades (sin diseño Pencil, on-brand) |

---

## Mock-first → real backend (phase 2)

Every repository is an abstract interface (`data/repositories/repositories.dart`)
with a `Mock*` implementation. The providers throw by default and are overridden
with the mocks in `main.dart`. To connect the real Python stack, add
`Http*Repository` classes and change **only** the overrides:

```dart
ProviderScope(
  overrides: [
    registryRepositoryProvider.overrideWithValue(HttpRegistryRepository(baseUrl)),
    // …the other three…
  ],
  child: const AgentTrustApp(),
)
```

Domain models already serialize with the exact schema field names
(`principal_id`, `verification_rate`, `task.offer`, …), and `watch()` returns a
`Stream`, so the HTTP impl can back it with SSE/WebSocket/polling with no UI
change. Nothing in `features/` or `core/` references a repository implementation.

Deferred to phase 2 (out of scope for this mock-first v1): real HTTP calls,
ed25519 key generation/signing/identity, bearer-auth enforcement, real
competitive negotiation/counter-offers, and speech-to-text transcription.

---

## Known caveats & deliberate tradeoffs

Because this was written without a compiler, a few choices favor
correctness-by-hand over the newest APIs. All are easy to revisit:

- **Pinned stable versions.** `flutter_riverpod ^2.6`, `go_router ^14`. The 2026
  research recommended Riverpod 3 + codegen and go_router 17; those are the
  intended **upgrade path** once the app compiles and you can run `build_runner`.
- **Material Icons, not Lucide.** The design uses Lucide; this uses the closest
  built-in Material icons to avoid a fragile dependency. Swap in `lucide_icons`
  later for exact parity.
- **Audio is a pure-Flutter stub.** `features/request/widgets/audio_recorder_stub.dart`
  animates a waveform + timer with a `CustomPainter` and `Timer` — no plugin, no
  mic permission, no recording, no STT. It fills a sample description on stop.
- **Fonts via `google_fonts`** (Inter + Geist Mono) so no binaries are bundled.
  First run fetches + caches them. If `GoogleFonts.geistMono` is unavailable in
  your pinned `google_fonts`, bundle the `.ttf` or switch to another mono family
  in `core/theme/app_typography.dart`.
- **No fake status bar.** The design shows a mock status bar; a real app should
  use the OS status bar, so screens use `SafeArea` instead.
- **Light theme + localization deferred.** The app is dark-first and Spanish,
  matching the design; strings are inline (no `intl` message catalog yet).

## Tests

`test/domain/models_test.dart` covers the load-bearing model rules: neutral
reputation → null rate, offers never carry a reservation, and offer price
sorting / stepper order. Widget tests are a good next step once the SDK is set
up (`ProviderScope(overrides: […])` + `pumpWidget`).
