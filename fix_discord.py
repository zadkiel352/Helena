from pathlib import Path

target_path = Path(__file__).resolve().parent / "actions" / "discord_mode.py"
content = target_path.read_text(encoding="utf-8")

lines = content.splitlines(keepends=True)

# Find the start of send_audio_to_discord
send_audio_start = None
for i, line in enumerate(lines):
    if line.strip().startswith("def send_audio_to_discord"):
        send_audio_start = i
        break

print(f"send_audio_to_discord at line {send_audio_start + 1 if send_audio_start else 'not found'}")

# Header is lines 0-60 (1-61)
header = lines[:61]

# The corrupted function is from line 61 to send_audio_start - 1
# We replace it with the corrected function

corrected = '''def _on_discord_presence_event(event: dict) -> None:
    """Convierte eventos de presencia del canal en una intervención generada por la IA.
    
    V32.7: Rate limiting anti-loop: no responder a eventos de presencia si Helena
    acaba de hablar o si hubo un evento reciente (< 8s). Evita bucles de auto-respuesta.
    """
    ctx = _context
    try:
        kind = str(event.get("type") or "join")
        name = str(event.get("user_name") or "alguien")
        channel = str(event.get("channel_name") or "el canal")
        members = event.get("members") or []
        members_text = ", ".join(members) if isinstance(members, list) else str(members)

        # Rate limiting: evitar bucles de auto-respuesta
        now = time.time()
        if not hasattr(_on_discord_presence_event, "_last_presence_ts"):
            _on_discord_presence_event._last_presence_ts = 0.0
            _on_discord_presence_event._last_presence_kind = ""
            _on_discord_presence_event._last_presence_name = ""
        
        # Ignorar eventos muy frecuentes del mismo tipo/usuario (posible bucle)
        if (now - _on_discord_presence_event._last_presence_ts < 8.0 and
            _on_discord_presence_event._last_presence_kind == kind and
            _on_discord_presence_event._last_presence_name == name):
            _ui_log(f"[Discord] ⏭️ Evento de presencia ignorado (rate limit): {kind} {name}")
            return
        
        # También ignorar si Helena habló hace menos de 5s (evita respuesta a su propia salida)
        if ctx and hasattr(ctx, "_assistant_output_last_audio_ts"):
            if now - getattr(ctx, "_assistant_output_last_audio_ts", 0) < 5.0:
                _ui_log(f"[Discord] ⏭️ Evento de presencia ignorado (Helena acaba de hablar): {kind} {name}")
                return

        _on_discord_presence_event._last_presence_ts = now
        _on_discord_presence_event._last_presence_kind = kind
        _on_discord_presence_event._last_presence_name = name

        if kind == "join":
            prompt = (
                f"[EVENTO DISCORD PUBLICO - PRESENCIA] Entró {name} al canal {channel}. "
                f"Usuarios visibles ahora: {members_text}. "
                "Respondé en voz con UNA sola frase breve para el canal. "
                "Avisale a Leo si corresponde, por ejemplo 'Leito, entró X'. "
                "Tono gamer carismático, gracioso, de party; podés usar bardo amistoso como manko/petón/noob/NPC si queda natural. "
                "No uses detalles íntimos, sexuales ni romanticismo intenso."
            )
        else:
            prompt = (
                f"[EVENTO DISCORD PUBLICO - PRESENCIA] {name} salió del canal {channel}. "
                f"Usuarios visibles ahora: {members_text}. "
                "Respondé en voz con UNA sola frase breve para el canal, estilo gamer gracioso. "
                "No uses detalles íntimos, sexuales ni romanticismo intenso."
            )
        _ui_log(f"[Discord] 🤖 Evento de presencia enviado a Helena IA: {kind} {name}")
        if ctx and getattr(ctx, "audio_route", "local") == "discord":
            ctx.speak(prompt)
    except Exception as exc:
        _ui_log(f"[Discord] ⚠️ No pude procesar evento de presencia con IA: {exc}")
'''

# Build new content
new_lines = header + [corrected, "\n"] + lines[send_audio_start:]
new_content = "\n".join(new_lines)

target_path.write_text(new_content, encoding="utf-8")

print("File fixed successfully!")