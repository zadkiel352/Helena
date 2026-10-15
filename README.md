# Helena

Helena es un asistente de escritorio para Windows con interfaz gráfica, entrada y salida de voz, automatización del equipo, integración opcional con Discord y control del navegador mediante una extensión.

## Requisitos

- Windows
- Python y las dependencias indicadas en `requirements.txt`
- Claves de API para los servicios que quieras utilizar

## Instalación

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Crea la configuración local de claves a partir de la plantilla y agrega tus propias claves:

```powershell
Copy-Item config\api_keys.example.json config\api_keys.json
```

`config\api_keys.json`, `.env`, la configuración local del navegador, perfiles, logs y datos de memoria no se publican en Git.

## Ejecución

```powershell
python main.py
```

Para configurar el control del navegador, ejecuta:

```powershell
python setup.py --browser-setup
```

## Pruebas

```powershell
python -m unittest discover -s tests -v
```
