# Reproductor de música de Discord

El reproductor transmite audio al canal de voz de Helena y crea un panel con
controles en un canal de texto. El panel se edita al cambiar la canción,
pausar/reanudar o modificar el volumen; también muestra los próximos temas.

## Configuración

En `config/api_keys.json`, configurá el ID del canal de texto donde querés el
panel:

```json
{
  "discord_music_text_channel_id": "ID_DEL_CANAL"
}
```

Si `discord_music_text_channel_id` queda vacío o no se configura, se usa
`discord_text_channel_id`. El bot necesita permiso para ver el canal, enviar
mensajes y usar comandos/controles de aplicaciones.

Instalá las dependencias de Discord con
`pip install -r requirements_discord.txt`. La búsqueda por nombre usa `yt-dlp`;
la reproducción requiere que FFmpeg esté instalado y disponible en `PATH` (o
configurado mediante `ffmpeg_path`).

## Uso

Pedile a Helena que reproduzca un tema o una URL. El panel permite pausar,
reanudar, saltar, detener, ajustar el volumen, ver la lista, activar loop,
mezclar la cola y volver al tema anterior. Para búsquedas por nombre, yt-dlp transmite el audio directamente a
FFmpeg por una tubería. Así FFmpeg no tiene que volver a solicitar la URL
temporal a la fuente (lo que puede fallar con HTTP 403). Si no llega audio, el
panel conserva el tema e informa el error en lugar de confirmar una
reproducción que no empezó.
