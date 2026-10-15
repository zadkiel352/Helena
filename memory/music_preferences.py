# memory/music_preferences.py - Unified Music Preferences System for HELENA V35
# V35_9_UNIFIED_MUSIC_PREFERENCES_CORE: Centralized music preferences independent of platform
import json
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, List

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
MUSIC_PREFS_PATH = MEMORY_DIR / "music_preferences.json"
LONG_TERM_PATH = MEMORY_DIR / "long_term.json"


def _log(text: str) -> None:
    """Log music preferences messages."""
    print(f"[MusicPrefs] {text}")


def ensure_music_preferences_file() -> Dict:
    """Ensure music preferences file exists, create with migration if needed."""
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        
        if not MUSIC_PREFS_PATH.exists():
            # Migrate from long_term.json if it exists
            default_prefs = migrate_from_long_term_if_needed()
            MUSIC_PREFS_PATH.write_text(json.dumps(default_prefs, indent=2, ensure_ascii=False), encoding="utf-8")
            _log(f"created {MUSIC_PREFS_PATH}")
            return default_prefs
        
        return load_music_preferences()
    except Exception as exc:
        _log(f"error ensuring file: {exc}")
        _log(traceback.format_exc())
        return get_default_structure()


def get_default_structure() -> Dict:
    """Get default music preferences structure."""
    return {
        "liked_artists": [],
        "liked_tracks": [],
        "liked_genres": [],
        "recent_tracks": [],
        "disliked_artists": [],
        "disliked_tracks": [],
        "updated_at": ""
    }


def load_music_preferences() -> Dict:
    """Load music preferences from dedicated file."""
    try:
        _log(f"path={MUSIC_PREFS_PATH}")
        
        if not MUSIC_PREFS_PATH.exists():
            _log("source=music_preferences (creating)")
            return ensure_music_preferences_file()
        
        prefs = json.loads(MUSIC_PREFS_PATH.read_text(encoding="utf-8"))
        _log("source=music_preferences")
        _log("loaded")
        return prefs
    except Exception as exc:
        _log(f"load error: {exc}")
        _log(traceback.format_exc())
        return get_default_structure()


def save_music_preferences(data: Dict) -> None:
    """Save music preferences to dedicated file."""
    try:
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        MUSIC_PREFS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _log(f"saved {MUSIC_PREFS_PATH}")
    except Exception as exc:
        _log(f"save error: {exc}")
        _log(traceback.format_exc())


def migrate_from_long_term_if_needed() -> Dict:
    """Migrate music preferences from long_term.json to dedicated file."""
    if not LONG_TERM_PATH.exists():
        _log("long_term.json not found, no migration needed")
        return get_default_structure()
    
    try:
        long_term_data = json.loads(LONG_TERM_PATH.read_text(encoding="utf-8"))
        _log("found long_term.json, checking for music data")
        
        liked_artists = []
        liked_tracks = []
        
        # Migrate "Musica/Favoritos" -> liked_artists
        musica_favoritos = long_term_data.get("Musica", {}).get("Favoritos", "")
        if musica_favoritos:
            if isinstance(musica_favoritos, str):
                liked_artists = [a.strip() for a in musica_favoritos.split(",") if a.strip()]
            elif isinstance(musica_favoritos, list):
                liked_artists = [str(a).strip() for a in musica_favoritos if str(a).strip()]
        
        # Migrate "Canciones favoritas" -> liked_tracks
        canciones_favoritas = long_term_data.get("Canciones favoritas", "")
        if canciones_favoritas:
            if isinstance(canciones_favoritas, str):
                liked_tracks = [t.strip() for t in canciones_favoritas.split(",") if t.strip()]
            elif isinstance(canciones_favoritas, list):
                liked_tracks = [str(t).strip() for t in canciones_favoritas if str(t).strip()]
        
        migrated_data = get_default_structure()
        migrated_data["liked_artists"] = liked_artists
        migrated_data["liked_tracks"] = liked_tracks
        migrated_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        
        if liked_artists or liked_tracks:
            _log(f"migrated from long_term: {len(liked_artists)} artists, {len(liked_tracks)} tracks")
        else:
            _log("no music data found in long_term.json")
        
        return migrated_data
    except Exception as exc:
        _log(f"migration error: {exc}")
        _log(traceback.format_exc())
        return get_default_structure()


def add_liked_artist(name: str) -> str:
    """Add artist to liked artists."""
    try:
        prefs = load_music_preferences()
        liked = prefs.get("liked_artists", [])
        
        if name.lower() not in [a.lower() for a in liked]:
            liked.append(name)
            prefs["liked_artists"] = liked
            save_music_preferences(prefs)
            _log(f"liked artist added: {name}")
            return f"Agregué {name} a tus artistas favoritos."
        else:
            return f"{name} ya estaba en tus favoritos."
    except Exception as exc:
        _log(f"liked artist error: {exc}")
        _log(traceback.format_exc())
        return "Error al guardar artista favorito."


def add_liked_track(title: str, artist: Optional[str] = None, source: Optional[str] = None) -> str:
    """Add track to liked tracks."""
    try:
        prefs = load_music_preferences()
        liked = prefs.get("liked_tracks", [])
        
        # Create track entry
        track_entry = title
        if artist:
            track_entry = f"{artist} - {title}"
        
        if track_entry.lower() not in [t.lower() for t in liked]:
            liked.append(track_entry)
            prefs["liked_tracks"] = liked
            save_music_preferences(prefs)
            _log(f"liked track added: {track_entry}")
            return f"Agregué {track_entry} a tus temas favoritos."
        else:
            return f"{track_entry} ya estaba en tus favoritos."
    except Exception as exc:
        _log(f"liked track error: {exc}")
        _log(traceback.format_exc())
        return "Error al guardar tema favorito."


def add_liked_genre(name: str) -> str:
    """Add genre to liked genres."""
    try:
        prefs = load_music_preferences()
        liked = prefs.get("liked_genres", [])
        
        if name.lower() not in [g.lower() for g in liked]:
            liked.append(name)
            prefs["liked_genres"] = liked
            save_music_preferences(prefs)
            _log(f"liked genre added: {name}")
            return f"Agregué {name} a tus géneros favoritos."
        else:
            return f"{name} ya estaba en tus géneros favoritos."
    except Exception as exc:
        _log(f"liked genre error: {exc}")
        _log(traceback.format_exc())
        return "Error al guardar género favorito."


def add_recent_track(title: str, artist: Optional[str] = None, query: Optional[str] = None, source: Optional[str] = None) -> None:
    """Add track to recent tracks history."""
    try:
        prefs = load_music_preferences()
        recent = prefs.get("recent_tracks", [])
        
        # Add new track with ISO timestamp
        recent_entry = {
            "title": title,
            "artist": artist or "",
            "query": query or "",
            "source": source or "unknown",
            "played_at": time.strftime("%Y-%m-%dT%H:%M:%S")
        }
        
        # Remove duplicates and add to front
        recent = [r for r in recent if r.get("title") != title]
        recent.insert(0, recent_entry)
        
        # Keep only last 50
        recent = recent[:50]
        
        prefs["recent_tracks"] = recent
        save_music_preferences(prefs)
        _log(f"recent track added: {title}")
    except Exception as exc:
        _log(f"recent track error: {exc}")
        _log(traceback.format_exc())


def get_music_seed() -> str:
    """Get a random music seed from preferences for recommendations."""
    try:
        prefs = load_music_preferences()
        liked_artists = prefs.get("liked_artists", [])
        liked_tracks = prefs.get("liked_tracks", [])
        
        import random
        
        # Prefer artists
        if liked_artists:
            seed = random.choice(liked_artists)
            _log(f"selected seed=artist:{seed}")
            return seed
        
        # Fall back to tracks
        if liked_tracks:
            seed = random.choice(liked_tracks)
            _log(f"selected seed=track:{seed}")
            return seed
        
        _log("selected seed=none")
        return ""
    except Exception as exc:
        _log(f"get_music_seed error: {exc}")
        return ""


def get_music_status() -> str:
    """Get music preferences status."""
    try:
        prefs = load_music_preferences()
        exists = MUSIC_PREFS_PATH.exists()
        liked_artists = len(prefs.get("liked_artists", []))
        liked_tracks = len(prefs.get("liked_tracks", []))
        liked_genres = len(prefs.get("liked_genres", []))
        recent_tracks = len(prefs.get("recent_tracks", []))
        updated_at = prefs.get("updated_at", "never")
        
        status = f"""Memoria musical:
Ruta: {MUSIC_PREFS_PATH}
Existe: {"Sí" if exists else "No"}
Artistas favoritos: {liked_artists}
Temas favoritos: {liked_tracks}
Géneros favoritos: {liked_genres}
Tracks recientes: {recent_tracks}
Última actualización: {updated_at}"""
        
        # Check if long_term.json exists
        if LONG_TERM_PATH.exists():
            status += "\nNota: long_term.json existe pero no se usa para música."
        
        return status
    except Exception as exc:
        _log(f"get_music_status error: {exc}")
        return f"Error al obtener estado de memoria: {exc}"
