# Guia rapida de CODE LAB de Helena

CODE LAB tiene dos partes distintas:

1. Editor visual: el panel donde ves, pegas, abrís, guardas y ejecutas codigo.
2. Herramienta real de desarrollo: `code_helper`, que puede escribir, editar, optimizar, ejecutar o abrir archivos.

Que Helena diga "me pongo a trabajar" no alcanza como confirmacion. Una tarea real tiene que terminar con un recibo `CODE LAB RESULT`.

## Como saber si Helena cambio un archivo

Despues de un cambio real, busca en el HUD o SYSTEM algo con esta forma:

```text
CODE LAB RESULT
Action: edit
Status: SAVED
File: C:\Helena\main.py
File exists now: yes
Size: ...
SHA256: ...
backup: C:\Helena\backups\code_lab\...
Audit receipt: C:\Helena\logs\code_lab_last_operation.json
```

Estados importantes:

- `SAVED`: guardo cambios en disco.
- `SAVED_AND_RAN_OK`: guardo y ejecuto/probo sin error detectado.
- `SAVED_BUT_RUN_FAILED`: guardo, pero la prueba fallo.
- `DRY_RUN_NO_FILE_CHANGED`: mostro una vista previa; no escribio el archivo.
- `EXECUTED_NO_FILE_CHANGED`: ejecuto un archivo; no lo modifico.
- `OPENED_NO_FILE_CHANGED`: abrio un archivo en el editor; no lo modifico.
- `FAILED`: no pudo completar la accion; no tomes el cambio como aplicado.

El ultimo recibo queda en:

```text
C:\Helena\logs\code_lab_last_operation.json
```

El historial queda en:

```text
C:\Helena\logs\code_lab_audit.log
```

Los backups de archivos editados por CODE LAB quedan en:

```text
C:\Helena\backups\code_lab\
```

## Botones del panel CODE LAB

- `OPEN`: abre un archivo en el editor.
- `SAVE`: guarda el contenido actual sobre el archivo activo.
- `SAVE AS`: guarda el contenido actual en otro archivo.
- `RUN`: ejecuta codigo del editor para Python, Java o JavaScript.
- `COPY`: copia el codigo del editor al portapapeles.
- `SEND`: manda el codigo visible a Helena para analisis o trabajo.
- `CLEAR`: limpia el editor.

Importante: guardar con el boton `SAVE` solo guarda lo que esta visible en el editor. No significa que Helena haya hecho una edicion inteligente.

## Como pedir analisis sin cambios

Ejemplos:

```text
Helena, analiza este archivo y decime riesgos. No cambies nada.
```

```text
Helena, explicame este codigo. Solo HUD, sin editar archivos.
```

Resultado esperado: Helena usa HUD/texto y debe decir que fue solo analisis.

## Como pedir cambios reales

Usa frases concretas con archivo y accion:

```text
Helena, edita C:\Helena\actions\code_helper.py y agrega un log de auditoria. Es autodesarrollo de Helena, podes modificar el proyecto.
```

```text
Helena, optimiza C:\Helena\ui.py para que CODE LAB informe mejor el archivo activo. Hacelo real y mostrame el recibo.
```

```text
Helena, ejecuta C:\Helena\scripts\demo.py y decime la salida. No edites el archivo.
```

Para el propio proyecto Helena, conviene decir explicitamente:

```text
Esto es autodesarrollo de Helena, podes modificar archivos de C:\Helena.
```

Eso habilita `allow_self_edit=true` cuando corresponde. Sin esa autorizacion, CODE LAB puede bloquear la escritura para proteger el sistema.

## Como pedir una vista previa sin guardar

```text
Helena, hace un dry run de este cambio en C:\Helena\main.py: ...
```

Resultado esperado:

```text
Status: DRY_RUN_NO_FILE_CHANGED
```

Si ves ese estado, no se guardo nada.

## Donde guarda codigo nuevo

Si pedis crear codigo y no das ruta, CODE LAB usa por defecto:

```text
C:\Users\<tu_usuario>\Desktop\HelenaProjects\
```

Si queres controlar el destino, pedi una ruta completa:

```text
Helena, crea un script en C:\Helena\tools\mi_script.py que ...
```

## Cuando dice que no pudo reemplazar o guardar

Revisa el recibo:

- Si el estado es `FAILED`, el archivo no quedo confirmado.
- Si el motivo menciona `Self-edit blocked`, faltaba autorizacion clara de autodesarrollo.
- Si menciona `Protected file blocked`, intento tocar `.env` o `api_keys.json`, que estan protegidos.
- Si menciona `Path outside CODE LAB safe roots`, la ruta no esta permitida.

## Checklist para verificar un cambio

1. Mira que exista `CODE LAB RESULT`.
2. Confirma `Status: SAVED` o `SAVED_AND_RAN_OK`.
3. Copia la ruta de `File`.
4. Mira `Backup` si queres saber donde quedo la version anterior.
5. Abre `C:\Helena\logs\code_lab_last_operation.json` para ver el ultimo recibo tecnico.
6. Si queres maxima seguridad, pedi: "Helena, ejecuta py_compile sobre los archivos que tocaste".


Mini regla práctica: si no ves CODE LAB RESULT con Status: SAVED o SAVED_AND_RAN_OK, no asumas que el código fue cambiado.

