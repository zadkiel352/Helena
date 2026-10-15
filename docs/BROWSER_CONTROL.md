# Browser Control - Documentación

## Overview

Helena Browser Control permite controlar navegadores Chromium (Opera, Chrome, Edge, Brave) mediante tres backends:

1. **EXTENSION_BACKEND** (prioridad máxima) - Usa la extensión Helena Browser Controller
2. **CDP_BACKEND** (prioridad media) - Usa Chrome DevTools Protocol
3. **SYSTEM_FALLBACK** (prioridad baja) - Usa atajos de teclado del sistema

## Modos de Operación

### 1. Modo Automático Seguro (Recomendado para GitHub/Setup)

Helena puede configurar automáticamente un navegador con perfil aislado y extensión cargada, sin tocar tu perfil personal.

**Ventajas:**
- ✅ No toca tu perfil personal del navegador
- ✅ Extensión cargada automáticamente
- ✅ Perfil aislado para Helena
- ✅ Listo para usar inmediatamente
- ✅ Seguro para subir a GitHub

**Cómo configurar:**

Ejecuta el setup automático:
```bash
python setup.py --browser-setup
```

Esto creará:
- `config/browser_config.json` - Configuración de browser control
- `launchers/start_helena_browser_{navegador}.bat` - Launchers con CDP y extensión
- `launchers/start_helena_browser_{navegador}_extension_only.bat` - Launchers sin CDP
- `browser_profiles/{navegador}_helena/` - Perfiles aislados

**Cómo usar:**

Simplemente ejecuta el launcher correspondiente:
```bash
# Con CDP (recomendado para control completo)
C:\Helena\launchers\start_helena_browser_opera.bat

# Sin CDP (solo extensión WebSocket)
C:\Helena\launchers\start_helena_browser_opera_extension_only.bat
```

El navegador se iniciará con:
- Perfil aislado: `C:\Helena\browser_profiles\opera_helena`
- Extensión cargada automáticamente: `--load-extension=C:\Helena\opera_extension`
- CDP activo (opcional): `--remote-debugging-port=9222`

**Diagnóstico:**

Para verificar el estado:
```bash
python setup.py --diagnose
```

**Instalación Manual en Perfil Personal:**

Si prefieres usar tu navegador personal (sin perfil aislado):
```bash
python setup.py --manual-install
```

Esto mostrará instrucciones para instalar manualmente la extensión en tu perfil.

### 2. Modo Extensión Manual (Perfil Personal)

La extensión "Helena Browser Controller" se conecta al WebSocket local de Helena y proporciona control completo del navegador.

**Ventajas:**
- Control completo de pestañas
- Navegación precisa
- Detección automática de cambios
- Soporte para múltiples navegadores

**Requisitos:**
- Instalar la extensión en el navegador
- Helena debe estar ejecutándose
- Puerto WebSocket: 8766

**Instalación Manual:**

1. Abre tu navegador (Opera, Chrome, Edge)
2. Ve a la página de extensiones:
   - Opera/Chrome: `chrome://extensions/`
   - Edge: `edge://extensions/`
3. Activa "Modo desarrollador"
4. Haz clic en "Cargar extensión sin empaquetar"
5. Selecciona: `C:\Helena\opera_extension`

⚠️ **Nota:** Esto instalará la extensión en tu perfil personal. Helena no instala extensiones silenciosamente por seguridad.

**Solución de problemas "Desconectado":**

Si el popup muestra "Desconectado":

1. Verifica que Helena esté ejecutándose
2. Verifica el puerto en el popup (debe ser 8766)
3. Si muestra error de conexión, Helena puede no estar escuchando en el puerto correcto
4. Haz clic en "Actualizar lista" para forzar reconexión
5. La extensión intentará reconectarse automáticamente cada 2-10 segundos

### 3. Modo CDP (Chrome DevTools Protocol)

CDP permite controlar navegadores que fueron iniciados con el flag de remote debugging.

**Ventajas:**
- No requiere extensión
- Control programático completo
- Ideal para automatización

**Requisitos:**
- Navegador iniciado con `--remote-debugging-port=9222`
- Puerto CDP: 9222

**Cómo usar:**

Usa el launcher de Helena:
```bash
python tools/launch_browser_debug.py opera
python tools/launch_browser_debug.py chrome
python tools/launch_browser_debug.py edge
python tools/launch_browser_debug.py brave
```

O usa los scripts .bat en la carpeta `launchers`:
- `start_helena_browser_opera.bat` (con CDP y extensión)
- `start_helena_browser_opera_extension_only.bat` (solo extensión, sin CDP)

**Importante:** Los launchers usan perfiles separados para evitar conflictos con tu perfil personal:
- `C:\Helena\browser_profiles\opera_helena`
- `C:\Helena\browser_profiles\chrome_helena`
- `C:\Helena\browser_profiles\edge_helena`

### 4. Modo Fallback del Sistema

Si no hay extensión ni CDP disponible, Helena usa atajos de teclado del sistema.

**Ventajas:**
- Funciona sin configuración adicional
- Compatible con cualquier aplicación

**Limitaciones:**
- Solo control básico
- Requiere que el navegador tenga el foco
- Menos preciso

## Diferencia: Extensión vs CDP

| Característica | Extensión | CDP |
|---|---|---|
| **Requiere instalación** | Sí (manual o automática) | No (solo flags de inicio) |
| **Control de pestañas** | Completo | Completo |
| **Navegación** | Completa | Completa |
| **Perfil aislado** | Opcional (launcher) | Opcional (launcher) |
| **Setup inicial** | Cargar extensión | Iniciar con flags |
| **Ideal para** | Uso diario, perfil personal | Automatización, testing |

## Cómo Resetear Perfil Aislado

Si el perfil aislado de Helena tiene problemas:

1. **Cerrar el navegador** completamente
2. **Eliminar el perfil:**
   ```bash
   rmdir /s /q C:\Helena\browser_profiles\opera_helena
   ```
3. **Ejecutar el launcher nuevamente** - se creará un perfil fresco

⚠️ **No elimines tu perfil personal del navegador.** Solo elimina los perfiles en `C:\Helena\browser_profiles\`.

## Qué NO Subir a GitHub

Para mantener tu privacidad y seguridad, **NO subas** a GitHub:

- `browser_profiles/` - Perfiles de navegador aislados (contienen cookies, historial)
- `config/api_keys.json` - API keys reales
- `.env` - Variables de entorno con secrets
- `tokens/` - Tokens de autenticación
- `sessions/` - Sesiones activas
- `cookies/` - Cookies del navegador
- `backups/` - Backups del sistema
- `reports/` - Reportes de auditoría
- `logs/` - Logs del sistema
- `__pycache__/` - Cache de Python
- `*.pyc` - Bytecode compilado
- `*.log` - Archivos de log
- `memory/long_term.json` - Memoria a largo plazo
- `memory/music_preferences.json` - Preferencias musicales

**Sí puedes subir:**
- `config/api_keys.example.json` - Ejemplo sin datos reales
- `config/browser_config.example.json` - Ejemplo de configuración
- `opera_extension/` - Código de la extensión (no contiene datos personales)
- `tools/` - Scripts y herramientas
- `docs/` - Documentación

## Seguridad y Aislamiento de Perfil

### Modo Seguro Recomendado

Helena usa perfiles aislados para evitar exponer tus datos personales:

**Características de seguridad:**
- ✅ Perfil aislado: `C:\Helena\browser_profiles\opera_helena`
- ✅ No toca tu perfil personal del navegador
- ✅ No lee cookies ni contraseñas
- ✅ No usa permisos elevados (sin nativeMessaging)
- ✅ Sin content_scripts en <all_urls>
- ✅ Solo comunicación WebSocket con localhost

### Permisos de la Extensión (Versión 1.1)

La extensión Helena Browser Controller v1.1 tiene permisos mínimos:

**Permisos actuales:**
- `tabs` - Acceso a pestañas (necesario para listar/cambiar pestañas)
- `storage` - Almacenamiento local (para configuración de la extensión)
- `activeTab` - Acceso a la pestaña activa (permiso más restrictivo)

**Permisos eliminados por seguridad:**
- ❌ `nativeMessaging` - Eliminado (permiso elevado innecesario)
- ❌ Content scripts en `<all_urls>` - Eliminado (solo hacía console.log)
- ❌ Host permissions `http://` - Solo `ws://` para WebSocket

**Host permissions:**
- `ws://localhost:8766/*` - Puerto principal
- `ws://localhost:8765/*` - Puerto fallback
- `ws://127.0.0.1:8766/*` - Fallback IP
- `ws://127.0.0.1:8765/*` - Fallback IP

### Cómo Reinstalar la Extensión

Si necesitas reinstalar la extensión:

1. **Desactivar extensión actual:**
   - Ve a `chrome://extensions/`
   - Desactiva "Helena Browser Controller"

2. **Eliminar extensión:**
   - Haz clic en "Eliminar"
   - Confirma la eliminación

3. **Recargar extensión:**
   - Haz clic en "Cargar extensión sin empaquetar"
   - Selecciona: `C:\Helena\opera_extension`

### Cómo Revocar Permisos

Para revocar permisos de la extensión:

1. Ve a `chrome://extensions/`
2. Haz clic en "Detalles" en "Helena Browser Controller"
3. En "Permisos del sitio", haz clic en "Borrar datos del sitio"
4. O desactiva la extensión completamente

### Diagnóstico de Seguridad

Para verificar el estado de seguridad del navegador:

```
"Helena, diagnóstico de seguridad del navegador"
```

Esto mostrará:
- Estado de conexión de extensión y CDP
- Verificación de perfil aislado
- Estado de .gitignore
- Permisos de la extensión
- Recomendaciones de seguridad

### Advertencia: No Usar Perfil Personal

⚠️ **Nunca uses tu perfil personal para automatización avanzada.**

Si instalas la extensión en tu perfil personal:
- Helena tendrá acceso a tus cookies, historial y datos personales
- No hay aislamiento de seguridad
- Los datos podrían exponerse si hay vulnerabilidades

**Si ya instalaste la extensión en tu perfil personal:**
1. Desinstala la extensión de tu perfil personal
2. Usa el launcher con perfil aislado
3. La extensión se cargará automáticamente en el perfil aislado

### Cómo Diagnosticar Desconexión

Si la extensión muestra "Desconectado":

1. **Verifica que Helena esté ejecutándose**
   - Debes ver `[BrowserBridge] extension connected` en los logs

2. **Verifica el puerto**
   - El popup debe mostrar puerto 8766
   - Si muestra 8765, está usando fallback

3. **Reconexión automática**
   - La extensión intenta reconectarse cada 2-10 segundos
   - Haz clic en "Actualizar lista" en el popup

4. **Usa el launcher**
   - Ejecuta: `C:\Helena\launchers\start_helena_browser_opera.bat`
   - Esto asegura perfil aislado y extensión cargada

5. **Diagnóstico de seguridad**
   - Ejecuta: "Helena, diagnóstico de seguridad del navegador"
   - Verifica que .gitignore excluya browser_profiles/

## Acciones Disponibles

### Listar Pestañas
```
"Helena, listá mis pestañas"
"Helena, qué pestañas tengo"
"Helena, ver pestañas"
```

### Navegar
```
"Helena, abrí YouTube"
"Helena, navegar a https://example.com"
"Helena, ir a google.com"
```

### Buscar
```
"Helena, buscá Ramones en YouTube"
"Helena, buscar cómo programar en Python"
```

### Nueva Pestaña
```
"Helena, nueva pestaña"
"Helena, abrir pestaña"
```

### Cerrar Pestaña
```
"Helena, cerrar pestaña"
"Helena, cerrar esta pestaña"
```

### Cerrar Pestaña Específica (requiere extensión)
```
"Helena, cerrar la pestaña de YouTube"
"Helena, cerrar pestaña que diga Facebook"
```

### Cambiar a Pestaña (requiere extensión)
```
"Helena, ir a la pestaña de Gmail"
"Helena, cambiar a pestaña de GitHub"
```

### Recargar
```
"Helena, recargar página"
"Helena, refrescar"
```

### Navegación
```
"Helena, atrás"
"Helena, volver"
"Helena, adelante"
```

### Scroll
```
"Helena, scroll hacia abajo"
"Helena, desplazar hacia arriba"
```

### Diagnóstico
```
"Helena, diagnóstico del navegador"
"Helena, estado del navegador"
```

## Backend Hierarchy

Helena intenta los backends en este orden:

1. **EXTENSION_BACKEND** - Si la extensión está conectada
2. **CDP_BACKEND** - Si hay un navegador con remote debugging
3. **SYSTEM_FALLBACK** - Atajos de teclado

Puedes forzar un backend específico:
```
"Helena, listá mis pestañas con backend cdp"
"Helena, abrí YouTube con backend extension"
```

## Puertos

- **WebSocket:** 8766 (extensión)
- **CDP:** 9222 (remote debugging)

La extensión intentará conectarse a:
- `ws://localhost:8766` (prioridad)
- `ws://localhost:8765` (fallback)
- `ws://127.0.0.1:8766` (fallback)
- `ws://127.0.0.1:8765` (fallback)

## Permisos de la Extensión

La extensión requiere:
- `tabs` - Acceso a pestañas
- `storage` - Almacenamiento local
- `activeTab` - Acceso a la pestaña activa
- `host_permissions` - Conexión a localhost:8765/8766

## Seguridad

Helena incluye medidas de seguridad:

1. **Bloqueo de páginas sensibles:** No automatiza páginas bancarias, de login o de pagos sin confirmación explícita
2. **No lectura de contraseñas:** No lee campos de password ni tokens
3. **Confirmación para acciones destructivas:** Pide confirmación antes de cerrar múltiples pestañas
4. **Perfiles separados:** CDP usa perfiles separados para no afectar tu perfil personal

## Configuración

### Archivo de Configuración

`config/browser_config.json` (creado por setup.py):
```json
{
  "browser_ws_port": 8766,
  "cdp_port": 9222,
  "browser_preferred": "opera",
  "extension_path": "C:\\Helena\\opera_extension",
  "browser_profiles": {
    "opera": "C:\\Helena\\browser_profiles\\opera_helena",
    "chrome": "C:\\Helena\\browser_profiles\\chrome_helena",
    "edge": "C:\\Helena\\browser_profiles\\edge_helena"
  },
  "detected_browsers": {
    "opera": "C:\\Program Files\\Opera\\launcher.exe"
  }
}
```

### Setup

Para configurar browser control:
```bash
python setup.py --browser-setup
```

Para ver qué se configuraría sin hacer cambios:
```bash
python setup.py --browser-setup --dry-run
```

## Desactivar Browser Control

Si no deseas usar browser control:

1. **Desactivar extensión:**
   - Ve a `chrome://extensions/`
   - Desactiva "Helena Browser Controller"

2. **No iniciar navegadores con CDP:**
   - No uses los launchers de Helena
   - Inicia navegadores normalmente

3. **Comentar en código:**
   - En `main.py`, comenta la importación de `browser_control`

## Troubleshooting

### Extensión muestra "Desconectado"

1. Verifica que Helena esté ejecutándose
2. Revisa los logs de Helena para "[BrowserBridge] extension connected"
3. Verifica que ningún otro programa esté usando el puerto 8766
4. Recarga la extensión en `chrome://extensions/`

### CDP no funciona

1. Asegúrate de iniciar el navegador con el launcher de Helena
2. Verifica que el navegador tenga el flag `--remote-debugging-port=9222`
3. Prueba acceder a `http://localhost:9222/json` en tu navegador
4. Si no responde, el puerto puede estar en uso

### Atajos de teclado no funcionan

1. Asegúrate de que el navegador tenga el foco
2. Verifica que no haya otra aplicación interceptando las teclas
3. Prueba manualmente: Ctrl+T (nueva pestaña), Ctrl+W (cerrar pestaña)

## Logs

Helena logs relevantes:
- `[BrowserBridge] extension connected` - Extensión conectada
- `[BrowserBridge] tabs received: N` - Pestañas recibidas
- `[BrowserBridge] extension disconnected` - Extensión desconectada
- `[CDP]` - Mensajes del backend CDP
- `[Navegador]` - Mensajes de browser_control.py

## Soporte de Navegadores

### Opera
- ✅ Extensión: Soportado
- ✅ CDP: Soportado
- ✅ Fallback: Soportado

### Chrome
- ✅ Extensión: Soportado
- ✅ CDP: Soportado
- ✅ Fallback: Soportado

### Edge
- ✅ Extensión: Soportado
- ✅ CDP: Soportado
- ✅ Fallback: Soportado

### Brave
- ✅ Extensión: Soportado
- ✅ CDP: Soportado
- ✅ Fallback: Soportado

### Firefox
- ❌ Extensión: No soportado (requiere manifest diferente)
- ❌ CDP: No soportado
- ✅ Fallback: Soportado

## Archivos Relacionados

- `actions/browser_control.py` - Lógica de control de navegador
- `websocket_server.py` - Servidor WebSocket para la extensión
- `opera_extension/` - Código de la extensión
- `tools/launch_browser_debug.py` - Launcher para CDP
- `config/browser_config.json` - Configuración de browser control
- `setup.py` - Script de setup con opción --browser-setup

## Contribución

Para agregar soporte para nuevas acciones:

1. Agrega la acción en `browser_control.py`
2. Si requiere extensión, agrega el comando en `opera_extension/background.js`
3. Actualiza esta documentación
