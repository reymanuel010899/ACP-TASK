# 📱 GUÍA DE CONFIGURACIÓN - APP MÓVIL AGENTTRUST

## ✅ LO QUE YA HEMOS HECHO

- ✅ Instalado Flutter SDK 3.24.0+
- ✅ Actualizado Flutter a la última versión estable
- ✅ Descargado todas las dependencias del proyecto
- ✅ Compilando APK en debug mode

## 📋 PANTALLAS DE LA APP

### 1. **HOME SCREEN** (`home_screen.dart`)
- Dashboard principal
- Resumen de tareas recientes
- Estadísticas de reputación
- Botones de acceso rápido

### 2. **EXPLORE AGENTS** (`explore_screen.dart`)
- Lista de proveedores disponibles
- Mostrar reputación ⭐ de cada proveedor
- Filtrar por capability (Terraform, API testing, etc.)
- Ver detalles del proveedor
- Seleccionar para contratar

### 3. **REGISTER AGENT** (`register_agent_screen.dart`)
- Formulario para registrar nuevo proveedor
- Ingresar URL del agente
- Configurar capabilities
- Establecer precio de base
- Subir a registry

### 4. **CREATE TASK** (`task_request_screen.dart`)
- Describir tarea en lenguaje natural
- Seleccionar proveedor de lista
- Ver detalles del proveedor (reputación, precio)
- Enviar solicitud
- Ver ofertas recibidas

### 5. **TASK PROGRESS** (`task_progress_screen.dart`)
- Ver progreso en tiempo real
- Mostrar evidencia del trabajo ejecutado
- Resultado de verificación ✅/❌
- Cambio de reputación del proveedor
- Historial de la tarea

### 6. **PROFILE SCREEN** (`profile_screen.dart`)
- Información del usuario
- Historial completo de tareas
- Reputación acumulada
- Configuración de preferencias
- Logout

---

## 🚀 CÓMO INSTALAR EN TU CELULAR

### Opción 1: Desde la APK compilada (RECOMENDADO)

```bash
# La APK se está compilando ahora en:
# mobile/build/app/outputs/apk/debug/app-debug.apk

# Una vez compilada, transferir al celular:
adb push mobile/build/app/outputs/apk/debug/app-debug.apk /sdcard/Download/

# O usar flutter para instalar directamente:
flutter install
```

### Opción 2: Compilar y ejecutar en emulador

```bash
# Iniciar emulador
emulator -avd YOUR_EMULATOR_NAME

# Compilar y ejecutar
cd mobile/
flutter run
```

### Opción 3: Compilar desde Android Studio

```bash
# Abrir proyecto en Android Studio
open -a "Android Studio" mobile/

# O desde terminal:
cd mobile/
open -a "Android Studio" .
```

---

## 📊 ARQUITECTURA DE LA APP

### Clean Architecture
```
lib/
├── domain/        ← Lógica pura de negocio
├── data/          ← Acceso a APIs y datos
├── features/      ← UI y screens
└── core/          ← Utilidades y temas
```

### State Management
- **flutter_riverpod** para manejo de estado
- Providers para datos remotos
- StateNotifiers para UI state

### Navegación
- **go_router** con rutas nombradas
- Bottom tab navigation
- Deep linking support

---

## 🔧 SOLUCIÓN DE PROBLEMAS

### Si tienes error de Gradle:
```bash
# Ya lo solucionamos actualizando Flutter
flutter upgrade

# Luego limpia y recompila
flutter clean
flutter pub get
flutter build apk --debug
```

### Si no se conecta a la API:
- Verifica que el backend esté corriendo en localhost
- Comprueba las URLs en `lib/core/api/`
- Usa `--registry-url` en la consola web si es modo conectado

### Si no puedes instalar en el celular:
```bash
# Habilitar USB debugging en el celular
# Conectar con cable USB

# Listar dispositivos conectados
adb devices

# Instalar APK
adb install -r mobile/build/app/outputs/apk/debug/app-debug.apk
```

---

## 📱 REQUISITOS DEL CELULAR

- Android 10+ (API level 29+)
- 100MB libre en almacenamiento
- USB debugging habilitado (si instalas por cable)

---

## 🎯 FLUJO DE USO TÍPICO

1. **Abrir app** → HOME SCREEN
2. **Explorar proveedores** → EXPLORE AGENTS
3. **Describir tarea** → CREATE TASK
4. **Ver progreso** → TASK PROGRESS
5. **Consultar historial** → PROFILE

---

## ✨ FEATURES IMPLEMENTADOS

- ✅ Material 3 Design
- ✅ Dark mode support
- ✅ Responsive layout (phone/tablet)
- ✅ HTTP client with error handling
- ✅ Local caching (if needed)
- ✅ Riverpod state management
- ✅ Go router navigation

---

## 📦 DEPENDENCIAS PRINCIPALES

```yaml
flutter_riverpod: ^2.6.1    # State management
go_router: ^14.6.0          # Navigation
google_fonts: ^6.2.1        # Typography
http: ^1.2.0                # HTTP client
```

---

## 🚀 PRÓXIMOS PASOS

Una vez que tengas la APK instalada:

1. Abre la app
2. Explora las diferentes pantallas
3. Conecta al backend (registry + verificador)
4. Crea una tarea de prueba
5. Vé el resultado verificado

---

**Estado actual:** 
- ✅ Flutter instalado y actualizado
- ✅ Dependencias descargadas
- ⏳ APK compilándose...

La APK estará lista en pocos minutos.
