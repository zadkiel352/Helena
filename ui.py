# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import ctypes
import math
import os
import platform
import random
import subprocess
import sys

# --- HELENA V32.3: subprocess silencioso para HUD metrics ---
def _helena_hidden_startupinfo():
    """Evita ventanas fugaces de cmd/powershell/conhost en Windows."""
    if sys.platform != "win32":
        return None
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return si
    except Exception:
        return None


def _helena_run_hidden(cmd, **kwargs):
    """subprocess.run con CREATE_NO_WINDOW en Windows.

    Se usa para sensores del HUD: nvidia-smi, PowerShell/WMI y pruebas rápidas.
    No cambia la salida capturada; solo oculta la ventana de consola.
    """
    if sys.platform == "win32":
        try:
            kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
        si = _helena_hidden_startupinfo()
        if si is not None:
            kwargs.setdefault("startupinfo", si)
    return subprocess.run(cmd, **kwargs)
# --- FIN HELENA V32.3 ---

import threading
import time
from pathlib import Path

import psutil
from utils.ui_tasks import build_project_summary, execute_code, read_code_file

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QRegularExpression, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase, QTextCharFormat, QSyntaxHighlighter,
    QAction, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar, QComboBox, QStackedWidget, QGridLayout,
    QMenu, QSystemTrayIcon,
)
from utils.ui_tasks import find_http_url_spans, is_conversation_line


class _BackgroundTaskSignals(QObject):
    result = pyqtSignal(object)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"
ICON_FILE  = BASE_DIR / "assets" / "helena_icon.ico"

_DEFAULT_W, _DEFAULT_H = 1366, 768
_MIN_W,     _MIN_H     = 1120, 650
_LEFT_W  = 250
_RIGHT_W = 420

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


def _set_windows_app_user_model_id():
    """Fuerza a Windows a usar el icono propio de HELENA en la barra de tareas.

    Cuando se ejecuta con `python main.py`, Windows puede agrupar la ventana bajo
    python.exe y mostrar el icono de Python. El AppUserModelID separa HELENA de
    python.exe para que tome el QIcon de la app/ventana.
    """
    if platform.system() != "Windows":
        return
    try:
        app_id = "LeoZadkiel.Helena.CoreV64"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def _helena_icon():
    try:
        if ICON_FILE.exists():
            return QIcon(str(ICON_FILE))
        png = BASE_DIR / "assets" / "helena_icon.png"
        if png.exists():
            return QIcon(str(png))
    except Exception:
        pass
    return QIcon()

class C:
    # Fondos y Paneles (Basados en el encaje negro y sombras profundas de la modelo)
    BG        = "#020205"  # Negro absoluto, fondo de pantalla puro
    PANEL     = "#08070d"  # Negro ultra oscuro con un ligerísimo matiz cálido
    PANEL2    = "#121018"  # Negro carbón para contrastes de sub-paneles
    DARK      = "#010103"  # Sombra base profunda
    BAR_BG    = "#0c0a07"  # Fondo de barras de carga (Marrón/Oro sumergido)

    # Bordes y Divisiones (Geometría fina con transiciones de Oro)
    BORDER    = "#3a2f1d"  # Oro viejo/bronce opaco para estados inactivos o sutiles
    BORDER_B  = "#8c6f3d"  # Oro pulido de intensidad media
    BORDER_A  = "#dfb15b"  # Oro brillante/dorado encendido (Mismo tono de los hilos del vestido)

    # Colores Primarios y Destacados (La luz principal del HUD)
    PRI       = "#d4af37"  # Oro metálico clásico (Texto principal, ondas de voz activas)
    PRI_DIM   = "#967b2c"  # Oro atenuado para etiquetas secundarias o estados de espera
    PRI_GHO   = "#1f180c"  # Brillo fantasma dorado (Fondo de botones seleccionados o focos)

    # Tonos de Piel y Contraste Cálido (Inspirado en el tono satinado de la modelo)
    ACC       = "#fcdbb0"  # Piel clara satinada / Champán (Ideal para destacar datos importantes)
    ACC2      = "#eadeca"  # Blanco marfil cálido / lino suave

    # Alertas, Micrófono y Labios (Basado exactamente en el Rojo Carmín de sus labios)
    RED       = "#b81d24"  # Rojo carmín profundo (Alertas críticas, sobrecargas de CPU)
    MUTED_C   = "#d92b36"  # Rojo vivo labial (Estado silenciado / MUTE)
    GREEN     = "#cca43b"  # Reemplazado por Oro Oliva para el "SYS OK" para no romper la estética
    GREEN_D   = "#8a6d25"  # Oro Oliva oscuro

    # Textos (Legibilidad cyberpunk de alta gama)
    TEXT      = "#f5ebd7"  # Blanco cálido/crema de alta legibilidad
    TEXT_DIM  = "#6e5d47"  # Sepia/bronce apagado para textos decorativos o de fondo
    TEXT_MED  = "#b09b7c"  # Oro viejo claro para subtítulos y descripciones
    WHITE     = "#d8f8ff"
    DARK      = "#050010"
    BAR_BG    = "#011520"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0
        self.gpu  = -1.0
        self.tmp  = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(6.0)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # NVIDIA
        try:
            r = _helena_run_hidden(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [float(v.strip()) for v in r.stdout.strip().split("\n") if v.strip()]
                if vals:
                    return sum(vals) / len(vals)
        except Exception:
            pass

        # AMD (Linux)
        if _OS == "Linux":
            try:
                r = _helena_run_hidden(
                    ["rocm-smi", "--showuse", "--csv"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    for line in r.stdout.strip().split("\n"):
                        parts = line.split(",")
                        if len(parts) >= 2:
                            try:
                                return float(parts[1].strip().replace("%", ""))
                            except ValueError:
                                pass
            except Exception:
                pass

            # Intel GPU (Linux)
            try:
                r = _helena_run_hidden(
                    ["intel_gpu_top", "-J", "-s", "500"],
                    capture_output=True, text=True, timeout=1
                )
                if r.returncode == 0 and "Render/3D" in r.stdout:
                    import re
                    m = re.search(r'"busy":\s*([\d.]+)', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        # macOS - powermetrics (GPU Engine)
        if _OS == "Darwin":
            try:
                r = _helena_run_hidden(
                    ["sudo", "-n", "powermetrics", "-n", "1", "-i", "500",
                     "--samplers", "gpu_power"],
                    capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0 and "GPU" in r.stdout:
                    import re
                    m = re.search(r'GPU\s+Active:\s+([\d.]+)%', r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            candidates = ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                          "cpu-thermal", "zenpower", "it8688"]
            for name in candidates:
                if name in temps:
                    entries = temps[name]
                    if entries:
                        return entries[0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass
        if _OS == "Darwin":
            try:
                r = _helena_run_hidden(
                    ["osx-cpu-temp"], capture_output=True, text=True, timeout=2
                )
                if r.returncode == 0:
                    import re
                    m = re.search(r"([\d.]+)", r.stdout)
                    if m:
                        return float(m.group(1))
            except Exception:
                pass

        if _OS == "Windows":
            try:
                r = _helena_run_hidden(
                    ["powershell", "-Command",
                     "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi).CurrentTemperature"],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0 and r.stdout.strip():
                    raw = float(r.stdout.strip().split("\n")[0])
                    return (raw / 10.0) - 273.15
            except Exception:
                pass

        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    """HELENA CORE V6 canvas.

    This version is not an overlay with fake HUD eyes/mouth.  It uses a close
    crop of the same transparent model plus real sprite layers derived from
    that same face: open/closed eyelids, iris patches and mouth phoneme states.
    """

    RIG_DIR = BASE_DIR / "assets" / "helena_rig"
    MODEL_FILE = RIG_DIR / "model_core.png"
    SPRITES = {
        # Full-canvas sprites exported manually from the same Photoshop canvas as model_core.png.
        # Every PNG must have the same size as model_core.png, so there are no more hand-tuned
        # coordinates for eyes/mouth. This removes the old alignment drift.
        "eyes_open": "eyes_open.png",
        "eyes_half": "eyes_half_closed.png",
        "eyes_closed": "eyes_closed.png",
        "mouth_0": "mouth_0_closed.png",
        "mouth_1": "mouth_1.png",
        "mouth_2": "mouth_2.png",
        "mouth_3": "mouth_3.png",
        "mouth_4": "mouth_4.png",
    }
    RIG_RECTS = {}

    # V37 Articulated Rig
    V37_RIG_DIR = BASE_DIR / "assets" / "helena_rig_v37"
    V37_LAYERS = {
        "preview_full": "preview_full.png",
        "body_base": "body_base.png",
        "head": "head.png",
        "neck": "neck.png",
        "hair_back": "hair_back.png",
        "hair_front": "hair_front.png",
        "left_upper_arm": "left_upper_arm.png",
        "left_forearm": "left_forearm.png",
        "left_hand": "left_hand.png",
        "right_upper_arm": "right_upper_arm.png",
        "right_forearm": "right_forearm.png",
        "right_hand": "right_hand.png",
        "dress_top_front": "dress_top_front.png",
        "skirt_clothes_front": "skirt_clothes_front.png",
        "eyes_open": "eyes_open.png",
        "eyes_half": "eyes_half_closed.png",
        "eyes_closed": "eyes_closed.png",
        "mouth_0": "mouth_0_closed.png",
        "mouth_1": "mouth_1.png",
        "mouth_2": "mouth_2.png",
        "mouth_3": "mouth_3.png",
        "mouth_4": "mouth_4.png",
    }

    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(520, 520)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted = False
        self.speaking = False
        self.state = "INITIALISING"

        self._tick = 0
        self._model_px: QPixmap | None = None
        self._fallback_px: QPixmap | None = None
        self._sprites: dict[str, QPixmap] = {}
        self._model_rect = QRectF()
        self._model_size = QSize(650, 1050)

        self._halo = 90.0
        self._halo_t = 90.0
        self._last_voice = time.time()
        self._rings = [0.0, 108.0, 224.0, 316.0]
        self._pulses = [0.0, 160.0, 320.0]
        self._particles: list[list[float]] = []
        self._fog: list[list[float]] = []

        # Real facial system.
        self._blink = 0.0
        self._blink_target = 0.0
        self._next_blink = random.randint(95, 210)
        self._double_blink = False
        self._eye_dx = 0.0
        self._eye_dy = 0.0
        self._eye_dx_t = 0.0
        self._eye_dy_t = 0.0
        self._next_eye = random.randint(70, 190)
        self._mouth_open = 0.0
        self._mouth_target = 0.0
        self._mouth_frame = 0
        self._breath = 0.0
        self._glow_phase = 0.0

        # V37 Articulated Rig
        self._v37_layers = {}
        self._v37_ready = False
        self._v37_size = QSize(1149, 1369)
        self._v37_pivots = {
            "head": (605, 405),
            "left_upper_arm": (780, 500),
            "left_forearm": (815, 830),
            "left_hand": (940, 1070),
            "right_upper_arm": (400, 470),
            "right_forearm": (350, 725),
            "right_hand": (200, 1080),
        }
        self._v37_motion_limits = {
            "head": 2.4,
            "upper_arm": 3.5,
            "forearm": 4.8,
            "hand": 3.5,
        }
        self._v37_layer_offsets = {}
        self._v37_debug_show_pivots = False
        self._v37_debug_show_layer_bounds = False
        self._v37_debug_show_model_rect = False
        self._v37_debug_show_gesture_overlay = True
        self._v37_gesture_overlay_position = "bottom_center"
        self._v37_arm_rig_mode = "simple"
        self._v37_debug_show_transformed_pivots = False
        self._debug_shortcuts = []
        self._v37_gestures = {}
        self._v37_current_gesture = None
        self._v37_gesture_until = 0.0
        self._v37_gesture_strength = 0.0
        self._v37_gesture_targets = {}
        self._v37_gesture_offsets = {}
        self._v37_gesture_delays = {}
        self._v37_gesture_variants = {}
        self._v37_current_gesture_variant = None
        self._v37_gesture_variants_enabled = True
        self._v37_gesture_oscillations = {}
        self._v37_gesture_expression = {}
        self._v37_gesture_started_at = 0.0
        self._v37_auto_policy = {}
        self._v37_auto_enabled = False
        self._v37_auto_next_decision_at = 0.0
        self._v37_auto_started_at = time.time()
        self._v37_last_auto_gesture_time = 0.0
        self._v37_last_manual_gesture_time = 0.0
        self._v37_last_auto_gesture_name = None
        self._v37_last_auto_by_name = {}
        self._v37_last_speaking_started_at = 0.0
        self._v37_previous_speaking = False
        self._v37_gesture_duration = 0.0
        self._v37_gesture_attack_seconds = 0.35
        self._v37_gesture_release_seconds = 0.45
        self._v37_manual_attack_seconds = 0.35
        self._v37_manual_release_seconds = 0.45
        self._v37_auto_attack_seconds = 0.55
        self._v37_auto_release_seconds = 0.65
        self._v37_gesture_stagger_enabled = False
        self._v37_gesture_micro_bounce_enabled = False
        self._v37_gesture_peak_logged = False
        self._v37_last_auto_gesture = 0.0
        self._v37_last_state_for_gesture = None
        self._v37_last_manual_gesture_time = 0.0
        self._v37_last_any_gesture_time = 0.0
        self._v37_gesture_source = None
        self._v37_gesture_lock_until = 0.0
        self._v37_auto_gestures_enabled = True
        self._v37_manual_debounce_seconds = 0.75
        self._v37_auto_min_interval_seconds = 12.0
        self._v37_manual_lock_extra_seconds = 0.35
        self._v37_auto_cannot_interrupt_manual = True
        self._v37_auto_cannot_interrupt_any_active_gesture = True
        self._v37_gesture_intensity_multiplier = 1.0
        self._v37_debug_gesture_state = False
        self._v37_gesture_limits = {}
        self._head_angle = 0.0
        self._head_angle_t = 0.0
        self._head_dx = 0.0
        self._head_dy = 0.0
        self._left_upper_angle = 0.0
        self._left_upper_angle_t = 0.0
        self._left_forearm_angle = 0.0
        self._left_forearm_angle_t = 0.0
        self._left_hand_angle = 0.0
        self._left_hand_angle_t = 0.0
        self._right_upper_angle = 0.0
        self._right_upper_angle_t = 0.0
        self._right_forearm_angle = 0.0
        self._right_forearm_angle_t = 0.0
        self._right_hand_angle = 0.0
        self._right_hand_angle_t = 0.0
        self._gesture_timer = 0

        # Final angles with gesture offsets
        self._head_angle_final = 0.0
        self._left_upper_angle_final = 0.0
        self._left_forearm_angle_final = 0.0
        self._left_hand_angle_final = 0.0
        self._right_upper_angle_final = 0.0
        self._right_forearm_angle_final = 0.0
        self._right_hand_angle_final = 0.0

        # Final offsets with gesture offsets
        self._head_dx_final = 0.0
        self._head_dy_final = 0.0
        self._left_upper_dx_final = 0.0
        self._left_upper_dy_final = 0.0
        self._left_forearm_dx_final = 0.0
        self._left_forearm_dy_final = 0.0
        self._left_hand_dx_final = 0.0
        self._left_hand_dy_final = 0.0
        self._right_upper_dx_final = 0.0
        self._right_upper_dy_final = 0.0
        self._right_forearm_dx_final = 0.0
        self._right_forearm_dy_final = 0.0
        self._right_hand_dx_final = 0.0
        self._right_hand_dy_final = 0.0

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()

        self._load_assets(face_path)
        self._setup_debug_shortcuts()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(16)

    def keyPressEvent(self, event):
        if not self._v37_ready:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key.Key_F5:
            self._reload_v37_meta()
        elif key == Qt.Key.Key_F6:
            self._toggle_v37_debug_pivots()
        elif key == Qt.Key.Key_F7:
            self._toggle_v37_debug_model_rect()
        elif key == Qt.Key.Key_F8:
            self._toggle_v37_debug_layer_bounds()
        else:
            super().keyPressEvent(event)

    def _setup_debug_shortcuts(self):
        """Setup keyboard shortcuts for V37 debug features."""
        if not self._v37_ready:
            return

        def _add_shortcut(key, callback):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(callback)
            self._debug_shortcuts.append(sc)

        _add_shortcut("F5", self._reload_v37_meta)
        _add_shortcut("F6", self._toggle_v37_debug_pivots)
        _add_shortcut("F7", self._toggle_v37_debug_model_rect)
        _add_shortcut("F8", self._toggle_v37_debug_layer_bounds)
        _add_shortcut("Ctrl+Alt+1", lambda: self._trigger_v37_gesture("saludo", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+2", lambda: self._trigger_v37_gesture("presentando", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+3", lambda: self._trigger_v37_gesture("pensando", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+4", lambda: self._trigger_v37_gesture("escuchando", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+5", lambda: self._trigger_v37_gesture("feliz", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+6", lambda: self._trigger_v37_gesture("enojada_leve", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+9", lambda: self._trigger_v37_gesture("debug_saludo_grande", source="manual", force=True))
        _add_shortcut("Ctrl+Alt+0", self._toggle_v37_gesture_overlay)
        _add_shortcut("Ctrl+Alt+A", self._toggle_v37_auto_gestures)

        print("[SYS] V37 debug shortcuts registered: F5/F6/F7/F8")
        print("[SYS] V37 gesture shortcuts registered: Ctrl+Alt+1-6, Ctrl+Alt+9 (debug), Ctrl+Alt+0 (toggle overlay), Ctrl+Alt+A (toggle auto gestures)")

    def _toggle_v37_debug_pivots(self):
        """Toggle debug pivot visualization."""
        self._v37_debug_show_pivots = not self._v37_debug_show_pivots
        print(f"[SYS] V37 debug pivots {'ON' if self._v37_debug_show_pivots else 'OFF'}")
        self.update()

    def _toggle_v37_debug_model_rect(self):
        """Toggle debug model rectangle visualization."""
        self._v37_debug_show_model_rect = not self._v37_debug_show_model_rect
        print(f"[SYS] V37 debug model rect {'ON' if self._v37_debug_show_model_rect else 'OFF'}")
        self.update()

    def _toggle_v37_debug_layer_bounds(self):
        """Toggle debug layer bounds visualization."""
        self._v37_debug_show_layer_bounds = not self._v37_debug_show_layer_bounds
        print(f"[SYS] V37 debug layer bounds {'ON' if self._v37_debug_show_layer_bounds else 'OFF'}")
        self.update()

    def _toggle_v37_gesture_overlay(self):
        """Toggle gesture debug overlay."""
        self._v37_debug_show_gesture_overlay = not self._v37_debug_show_gesture_overlay
        print(f"[SYS] V37 gesture overlay {'ON' if self._v37_debug_show_gesture_overlay else 'OFF'}")
        self.update()

    def _toggle_v37_auto_gestures(self):
        """Toggle auto gestures ON/OFF temporarily."""
        self._v37_auto_enabled = not self._v37_auto_enabled
        if self._v37_auto_enabled:
            self._v37_auto_started_at = time.time()
            self._schedule_next_v37_auto_decision()
        print(f"[SYS] V37 auto gestures {'ON' if self._v37_auto_enabled else 'OFF'}")

    def trigger_gesture(self, name: str):
        """Public method to trigger a V37 gesture."""
        return self._trigger_v37_gesture(name, source="manual", force=True)

    def _load_assets(self, face_path: str):
        model_path = self.MODEL_FILE if self.MODEL_FILE.exists() else Path(face_path)
        self._model_px = QPixmap(str(model_path))
        if self._model_px.isNull():
            self._model_px = None
        self._fallback_px = QPixmap(face_path) if Path(face_path).exists() else None
        for key, filename in self.SPRITES.items():
            px = QPixmap(str(self.RIG_DIR / filename))
            if not px.isNull():
                self._sprites[key] = px

        # Load V37 articulated rig layers
        for key, filename in self.V37_LAYERS.items():
            px = QPixmap(str(self.V37_RIG_DIR / filename))
            if not px.isNull():
                self._v37_layers[key] = px

        # Check if V37 has all required layers
        required_layers = [
            "preview_full", "body_base", "head", "hair_back", "hair_front",
            "left_upper_arm", "left_forearm", "left_hand",
            "right_upper_arm", "right_forearm", "right_hand",
            "eyes_open", "eyes_half", "eyes_closed",
            "mouth_0", "mouth_1", "mouth_2", "mouth_3", "mouth_4"
        ]
        self._v37_ready = all(key in self._v37_layers for key in required_layers)

        if self._v37_ready:
            # Load rig_meta.json if available
            rig_meta_path = self.V37_RIG_DIR / "rig_meta.json"
            try:
                if rig_meta_path.exists():
                    with open(rig_meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    # Load pivots
                    if "pivots" in meta:
                        for key, val in meta["pivots"].items():
                            if isinstance(val, list) and len(val) == 2:
                                self._v37_pivots[key] = (val[0], val[1])
                    # Load motion limits
                    if "motion_limits" in meta:
                        for key, val in meta["motion_limits"].items():
                            if isinstance(val, (int, float)):
                                self._v37_motion_limits[key] = float(val)
                    # Load layer offsets
                    if "layer_offsets" in meta:
                        for key, val in meta["layer_offsets"].items():
                            if isinstance(val, list) and len(val) == 2:
                                self._v37_layer_offsets[key] = (val[0], val[1])
                    # Load debug settings
                    if "debug" in meta:
                        debug = meta["debug"]
                        if isinstance(debug.get("show_pivots"), bool):
                            self._v37_debug_show_pivots = debug["show_pivots"]
                        if isinstance(debug.get("show_layer_bounds"), bool):
                            self._v37_debug_show_layer_bounds = debug["show_layer_bounds"]
                        if isinstance(debug.get("show_model_rect"), bool):
                            self._v37_debug_show_model_rect = debug["show_model_rect"]
                        if isinstance(debug.get("show_gesture_overlay"), bool):
                            self._v37_debug_show_gesture_overlay = debug["show_gesture_overlay"]
                        if isinstance(debug.get("gesture_overlay_position"), str):
                            self._v37_gesture_overlay_position = debug["gesture_overlay_position"]
                    # Load arm rig settings
                    if "arm_rig" in meta:
                        arm_rig = meta["arm_rig"]
                        if isinstance(arm_rig.get("mode"), str):
                            self._v37_arm_rig_mode = arm_rig["mode"]
                        if isinstance(arm_rig.get("debug_show_transformed_pivots"), bool):
                            self._v37_debug_show_transformed_pivots = arm_rig["debug_show_transformed_pivots"]
                    # Load gestures
                    if "gestures" in meta:
                        for gesture_name, gesture_data in meta["gestures"].items():
                            if isinstance(gesture_data, dict):
                                self._v37_gestures[gesture_name] = gesture_data
                    # Load gesture variants
                    if "gesture_variants" in meta:
                        self._v37_gesture_variants = meta["gesture_variants"]
                    # Load gesture control
                    if "gesture_control" in meta:
                        gc = meta["gesture_control"]
                        if isinstance(gc.get("auto_enabled"), bool):
                            self._v37_auto_gestures_enabled = gc["auto_enabled"]
                        if isinstance(gc.get("manual_debounce_seconds"), (int, float)):
                            self._v37_manual_debounce_seconds = float(gc["manual_debounce_seconds"])
                        if isinstance(gc.get("auto_min_interval_seconds"), (int, float)):
                            self._v37_auto_min_interval_seconds = float(gc["auto_min_interval_seconds"])
                        if isinstance(gc.get("manual_lock_extra_seconds"), (int, float)):
                            self._v37_manual_lock_extra_seconds = float(gc["manual_lock_extra_seconds"])
                        if isinstance(gc.get("auto_cannot_interrupt_manual"), bool):
                            self._v37_auto_cannot_interrupt_manual = gc["auto_cannot_interrupt_manual"]
                        if isinstance(gc.get("auto_cannot_interrupt_any_active_gesture"), bool):
                            self._v37_auto_cannot_interrupt_any_active_gesture = gc["auto_cannot_interrupt_any_active_gesture"]
                        if isinstance(gc.get("gesture_intensity_multiplier"), (int, float)):
                            self._v37_gesture_intensity_multiplier = float(gc["gesture_intensity_multiplier"])
                        if isinstance(gc.get("debug_gesture_state"), bool):
                            self._v37_debug_gesture_state = gc["debug_gesture_state"]
                        if isinstance(gc.get("manual_attack_seconds"), (int, float)):
                            self._v37_manual_attack_seconds = float(gc["manual_attack_seconds"])
                        if isinstance(gc.get("manual_release_seconds"), (int, float)):
                            self._v37_manual_release_seconds = float(gc["manual_release_seconds"])
                        if isinstance(gc.get("auto_attack_seconds"), (int, float)):
                            self._v37_auto_attack_seconds = float(gc["auto_attack_seconds"])
                        if isinstance(gc.get("auto_release_seconds"), (int, float)):
                            self._v37_auto_release_seconds = float(gc["auto_release_seconds"])
                        if isinstance(gc.get("gesture_stagger_enabled"), bool):
                            self._v37_gesture_stagger_enabled = gc["gesture_stagger_enabled"]
                        if isinstance(gc.get("gesture_micro_bounce_enabled"), bool):
                            self._v37_gesture_micro_bounce_enabled = gc["gesture_micro_bounce_enabled"]
                        if isinstance(gc.get("gesture_variants_enabled"), bool):
                            self._v37_gesture_variants_enabled = gc["gesture_variants_enabled"]
                    # Load auto gesture policy
                    if "auto_gesture_policy" in meta:
                        self._v37_auto_policy = meta["auto_gesture_policy"]
                        self._v37_auto_enabled = self._v37_auto_policy.get("enabled", False) and gc.get("auto_enabled", False)
                        if self._v37_auto_enabled:
                            self._schedule_next_v37_auto_decision()
                            mn = self._v37_auto_policy.get("decision_interval_min_seconds", 6.0)
                            mx = self._v37_auto_policy.get("decision_interval_max_seconds", 10.0)
                            cd = self._v37_auto_policy.get("global_min_interval_seconds", 28.0)
                            print(f"[SYS] V37 auto gesture cadence: decision every {mn}-{mx}s, cooldown={cd}s")
                    else:
                        self._v37_auto_enabled = False
                    # Load gesture limits
                    if "gesture_limits" in meta:
                        gl = meta["gesture_limits"]
                        if isinstance(gl.get("head"), (int, float)):
                            self._v37_gesture_limits["head"] = float(gl["head"])
                        if isinstance(gl.get("upper_arm"), (int, float)):
                            self._v37_gesture_limits["upper_arm"] = float(gl["upper_arm"])
                        if isinstance(gl.get("forearm"), (int, float)):
                            self._v37_gesture_limits["forearm"] = float(gl["forearm"])
                        if isinstance(gl.get("hand"), (int, float)):
                            self._v37_gesture_limits["hand"] = float(gl["hand"])
                    print("[SYS] V37 rig_meta loaded")
                else:
                    print("[SYS] V37 rig_meta unavailable, using default pivots")
            except Exception as e:
                print("[SYS] V37 rig_meta unavailable, using default pivots")
            print("[SYS] RIG MODE: ARTICULATED V37")
        else:
            print("[SYS] RIG MODE: FACIAL V6.4")

    def _reload_v37_meta(self):
        """Reload rig_meta.json without restarting the program."""
        if not self._v37_ready:
            return

        rig_meta_path = self.V37_RIG_DIR / "rig_meta.json"
        try:
            if rig_meta_path.exists():
                with open(rig_meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                # Load pivots
                if "pivots" in meta:
                    for key, val in meta["pivots"].items():
                        if isinstance(val, list) and len(val) == 2:
                            self._v37_pivots[key] = (val[0], val[1])
                # Load motion limits
                if "motion_limits" in meta:
                    for key, val in meta["motion_limits"].items():
                        if isinstance(val, (int, float)):
                            self._v37_motion_limits[key] = float(val)
                # Load layer offsets
                if "layer_offsets" in meta:
                    for key, val in meta["layer_offsets"].items():
                        if isinstance(val, list) and len(val) == 2:
                            self._v37_layer_offsets[key] = (val[0], val[1])
                # Load debug settings
                if "debug" in meta:
                    debug = meta["debug"]
                    if isinstance(debug.get("show_pivots"), bool):
                        self._v37_debug_show_pivots = debug["show_pivots"]
                    if isinstance(debug.get("show_layer_bounds"), bool):
                        self._v37_debug_show_layer_bounds = debug["show_layer_bounds"]
                    if isinstance(debug.get("show_model_rect"), bool):
                        self._v37_debug_show_model_rect = debug["show_model_rect"]
                print("[SYS] V37 rig_meta reloaded")
                self.update()
            else:
                print("[SYS] V37 rig_meta unavailable, keeping current values")
        except Exception as e:
            print("[SYS] V37 rig_meta reload failed, keeping current values")

    def _trigger_v37_gesture(self, name: str, duration: float | None = None, source: str = "manual", force: bool = False):
        """Trigger a V37 gesture by name with lock/debounce logic."""
        if not self._v37_ready:
            return False

        if name not in self._v37_gestures:
            return False

        now = time.time()

        # Manual source logic
        if source == "manual":
            # Apply debounce
            if not force and now - self._v37_last_manual_gesture_time < self._v37_manual_debounce_seconds:
                return False
            # Manual can interrupt auto, but not another manual unless forced
            if not force and self._v37_current_gesture is not None and self._v37_gesture_source == "manual":
                return False
            # Track manual gesture time
            self._v37_last_manual_gesture_time = now

        # Auto source logic
        elif source == "auto":
            # Check if auto gestures are enabled
            if not self._v37_auto_gestures_enabled:
                return False
            # Cannot interrupt manual gesture
            if self._v37_auto_cannot_interrupt_manual and self._v37_gesture_source == "manual":
                return False
            # Cannot interrupt any active gesture
            if self._v37_auto_cannot_interrupt_any_active_gesture and self._v37_current_gesture is not None:
                return False
            # Check lock
            if now < self._v37_gesture_lock_until:
                return False
            # Check min interval
            if now - self._v37_last_any_gesture_time < self._v37_auto_min_interval_seconds:
                return False

        # Select variant if enabled
        gesture = self._v37_gestures[name]
        self._v37_current_gesture_variant = None
        if self._v37_gesture_variants_enabled and name in self._v37_gesture_variants:
            variants = self._v37_gesture_variants[name]
            if variants and isinstance(variants, list):
                # Select variant by weight
                total_weight = sum(v.get("weight", 1.0) for v in variants)
                r = random.random() * total_weight
                cumulative = 0.0
                for variant in variants:
                    cumulative += variant.get("weight", 1.0)
                    if r <= cumulative:
                        gesture = variant
                        self._v37_current_gesture_variant = variant.get("name", "")
                        self._v37_gesture_oscillations = variant.get("oscillations", {})
                        self._v37_gesture_expression = variant.get("expression", {})
                        print(f"[SYS] V37 gesture variant: {name} -> {self._v37_current_gesture_variant}")
                        break

        gesture_duration = duration if duration is not None else gesture.get("duration", 2.0)

        self._v37_current_gesture = name
        self._v37_gesture_source = source
        self._v37_gesture_until = now + gesture_duration
        self._v37_gesture_lock_until = self._v37_gesture_until + (self._v37_manual_lock_extra_seconds if source == "manual" else 0.0)
        self._v37_last_any_gesture_time = now
        if source == "manual":
            self._v37_last_manual_gesture_time = now
        self._v37_gesture_targets = {
            "head": gesture.get("head", 0.0),
            "left_upper_arm": gesture.get("left_upper_arm", 0.0),
            "left_forearm": gesture.get("left_forearm", 0.0),
            "left_hand": gesture.get("left_hand", 0.0),
            "right_upper_arm": gesture.get("right_upper_arm", 0.0),
            "right_forearm": gesture.get("right_forearm", 0.0),
            "right_hand": gesture.get("right_hand", 0.0),
        }

        # Load gesture offsets
        offsets = gesture.get("offsets", {})
        self._v37_gesture_offsets = {
            "head": offsets.get("head", [0, 0]),
            "left_upper_arm": offsets.get("left_upper_arm", [0, 0]),
            "left_forearm": offsets.get("left_forearm", [0, 0]),
            "left_hand": offsets.get("left_hand", [0, 0]),
            "right_upper_arm": offsets.get("right_upper_arm", [0, 0]),
            "right_forearm": offsets.get("right_forearm", [0, 0]),
            "right_hand": offsets.get("right_hand", [0, 0]),
        }

        # Load gesture delays
        delays = gesture.get("delays", {})
        self._v37_gesture_delays = {
            "head": delays.get("head", 0.0),
            "left_upper_arm": delays.get("left_upper_arm", 0.0),
            "left_forearm": delays.get("left_forearm", 0.0),
            "left_hand": delays.get("left_hand", 0.0),
            "right_upper_arm": delays.get("right_upper_arm", 0.0),
            "right_forearm": delays.get("right_forearm", 0.0),
            "right_hand": delays.get("right_hand", 0.0),
        }

        # Set envelope timing based on source
        now = time.time()
        self._v37_gesture_started_at = now
        self._v37_gesture_duration = gesture_duration
        if source == "manual":
            self._v37_gesture_attack_seconds = self._v37_manual_attack_seconds
            self._v37_gesture_release_seconds = self._v37_manual_release_seconds
        else:
            self._v37_gesture_attack_seconds = self._v37_auto_attack_seconds
            self._v37_gesture_release_seconds = self._v37_auto_release_seconds

        # Reset peak logging
        self._v37_gesture_peak_logged = False

        print(f"[SYS] V37 gesture triggered: {name} source={source} duration={gesture_duration:.1f}")
        print(f"[SYS] V37 gesture accepted: {name} strength=0.0 targets={self._v37_gesture_targets}")
        return True

    def _ease_smoothstep(self, t: float) -> float:
        """Smoothstep easing function for smooth transitions."""
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    def _ease_out_cubic(self, t: float) -> float:
        """Ease out cubic function for fast release."""
        t = max(0.0, min(1.0, t))
        return 1.0 - pow(1.0 - t, 3.0)

    def _weighted_choice(self, weighted_dict):
        if not weighted_dict:
            return None
        total = sum(weighted_dict.values())
        if total <= 0:
            return None
        r = random.random() * total
        cumulative = 0.0
        for key, weight in weighted_dict.items():
            cumulative += weight
            if r <= cumulative:
                return key
        return None

    def _schedule_next_v37_auto_decision(self):
        mn = float(self._v37_auto_policy.get("decision_interval_min_seconds", 6.0))
        mx = float(self._v37_auto_policy.get("decision_interval_max_seconds", 10.0))
        if mx < mn:
            mx = mn
        self._v37_auto_next_decision_at = time.time() + random.uniform(mn, mx)

    def _maybe_trigger_v37_auto_gesture(self, speaking: bool):
        if not self._v37_ready:
            return
        if not self._v37_auto_enabled:
            return
        if not self._v37_auto_policy.get("enabled", False):
            return

        now = time.time()

        # Check decision cadence - only evaluate at scheduled intervals
        if now < self._v37_auto_next_decision_at:
            return

        # Schedule next decision before evaluating
        self._schedule_next_v37_auto_decision()

        # Startup grace
        startup_grace = self._v37_auto_policy.get("startup_grace_seconds", 18.0)
        if now - self._v37_auto_started_at < startup_grace:
            return

        if self._v37_current_gesture is not None:
            return
        if self._v37_gesture_strength > 0.05:
            return
        if now < self._v37_gesture_lock_until:
            return

        blocked_if_manual = self._v37_auto_policy.get("blocked_if_manual_recent_seconds", 12.0)
        if now - self._v37_last_manual_gesture_time < blocked_if_manual:
            return

        global_min_interval = self._v37_auto_policy.get("global_min_interval_seconds", 28.0)
        if now - self._v37_last_auto_gesture_time < global_min_interval:
            return

        blocked_states = self._v37_auto_policy.get("blocked_states", [])
        if self.state in blocked_states:
            return

        # Detect speaking started
        if speaking and not self._v37_previous_speaking:
            self._v37_last_speaking_started_at = now
        self._v37_previous_speaking = speaking

        blocked_if_speaking_started = self._v37_auto_policy.get("blocked_if_speaking_started_recently_seconds", 3.0)
        if now - self._v37_last_speaking_started_at < blocked_if_speaking_started:
            return

        # Determine state and pool
        chance = 0.0
        pool = {}

        if self.state in ("THINKING", "PENSANDO", "PROCESANDO"):
            chance = self._v37_auto_policy.get("thinking_chance", 0.40)
            pool = self._v37_auto_policy.get("allowed_while_thinking", {})
        elif speaking:
            chance = self._v37_auto_policy.get("speaking_chance", 0.22)
            pool = self._v37_auto_policy.get("allowed_while_speaking", {})
        elif self.state in ("LISTENING", "READY", "ACTIVE"):
            chance = self._v37_auto_policy.get("listening_chance", 0.10)
            pool = self._v37_auto_policy.get("allowed_while_listening", {})
        else:
            return

        if not pool or chance <= 0:
            return

        # Apply probability
        if random.random() > chance:
            return

        # Choose gesture
        name = self._weighted_choice(pool)
        if not name:
            return

        # Avoid repeating last gesture
        no_repeat = self._v37_auto_policy.get("no_repeat_last_gesture", True)
        if no_repeat and name == self._v37_last_auto_gesture_name:
            # Try to choose another
            pool_without_last = {k: v for k, v in pool.items() if k != name}
            if pool_without_last:
                name = self._weighted_choice(pool_without_last)
            else:
                return

        # Check same gesture interval
        same_gesture_interval = self._v37_auto_policy.get("same_gesture_min_interval_seconds", 60.0)
        if name in self._v37_last_auto_by_name:
            if now - self._v37_last_auto_by_name[name] < same_gesture_interval:
                # Try to choose another gesture
                pool_without_same = {k: v for k, v in pool.items() if k != name}
                if pool_without_same:
                    name = self._weighted_choice(pool_without_same)
                    if name in self._v37_last_auto_by_name:
                        if now - self._v37_last_auto_by_name[name] < same_gesture_interval:
                            return
                else:
                    return

        # Trigger gesture
        if self._trigger_v37_gesture(name, source="auto", force=False):
            self._v37_last_auto_gesture_time = now
            self._v37_last_auto_gesture_name = name
            self._v37_last_auto_by_name[name] = now
            next_check = self._v37_auto_next_decision_at - now
            print(f"[SYS] V37 auto gesture: {name} state={self.state} next_check={next_check:.1f}s")

    def _gesture_layer_strength(self, layer_name: str) -> float:
        """Calculate gesture strength for a specific layer with delay offset."""
        if not self._v37_current_gesture:
            return 0.0

        now = time.time()
        delay = self._v37_gesture_delays.get(layer_name, 0.0) if self._v37_gesture_stagger_enabled else 0.0
        elapsed = now - self._v37_gesture_started_at - delay

        duration = max(0.1, self._v37_gesture_duration)
        attack = max(0.05, self._v37_gesture_attack_seconds)
        release = max(0.05, self._v37_gesture_release_seconds)
        release_start = max(attack, duration - release)

        if elapsed < 0:
            return 0.0
        elif elapsed < attack:
            return self._ease_smoothstep(elapsed / attack)
        elif elapsed < release_start:
            strength = 1.0
            # Add micro bounce for manual gestures
            if self._v37_gesture_micro_bounce_enabled and self._v37_gesture_source == "manual":
                time_since_peak = elapsed - attack
                if time_since_peak < 0.25:
                    bounce = 1.0 + 0.06 * math.sin(time_since_peak * math.pi / 0.25)
                    strength = min(1.08, strength * bounce)
            return strength
        elif elapsed < duration:
            release_progress = (elapsed - release_start) / release
            return 1.0 - self._ease_out_cubic(release_progress)
        else:
            return 0.0

    def _update_v37_gesture(self):
        """Update gesture strength with envelope curve (attack, hold, release)."""
        if not self._v37_ready:
            return

        now = time.time()

        if self._v37_current_gesture:
            elapsed = now - self._v37_gesture_started_at
            duration = max(0.1, self._v37_gesture_duration)
            attack = max(0.05, self._v37_gesture_attack_seconds)
            release = max(0.05, self._v37_gesture_release_seconds)
            release_start = max(attack, duration - release)

            if elapsed < attack:
                # Attack phase: smooth ramp up to 1.0
                self._v37_gesture_strength = self._ease_smoothstep(elapsed / attack)
            elif elapsed < release_start:
                # Hold phase: maintain 1.0
                self._v37_gesture_strength = 1.0
                # Log peak when reaching 0.98+
                if not self._v37_gesture_peak_logged and self._v37_gesture_strength >= 0.98:
                    print(f"[SYS] V37 gesture full strength: {self._v37_current_gesture} strength={self._v37_gesture_strength:.2f}")
                    self._v37_gesture_peak_logged = True
            elif elapsed < duration:
                # Release phase: smooth ramp down to 0.0
                release_progress = (elapsed - release_start) / release
                self._v37_gesture_strength = 1.0 - self._ease_smoothstep(release_progress)
            else:
                # Gesture complete
                self._v37_gesture_strength = 0.0
                self._v37_current_gesture = None
                self._v37_gesture_source = None
                self._v37_gesture_targets = {}
                self._v37_gesture_offsets = {}
        else:
            self._v37_gesture_strength = 0.0

    def _v37_get_render_angles(self):
        """Get current render angles for diagnostic purposes."""
        return {
            "head": self._head_angle_final,
            "left_upper_arm": self._left_upper_angle_final,
            "left_forearm": self._left_forearm_angle_final,
            "left_hand": self._left_hand_angle_final,
            "right_upper_arm": self._right_upper_angle_final,
            "right_forearm": self._right_forearm_angle_final,
            "right_hand": self._right_hand_angle_final,
        }

    def _step(self):
        self._tick += 1
        now = time.time()
        speaking = self.speaking and not self.muted

        # Voice driven targets.
        if now - self._last_voice > (0.072 if speaking else 0.45):
            if speaking:
                self._halo_t = random.uniform(130, 190)
                self._mouth_target = random.choice([0.18, 0.36, 0.62, 0.86, 0.44])
                self._mouth_frame = random.choice([1, 2, 3, 4])
            elif self.state in ("THINKING", "PENSANDO", "PROCESANDO"):
                self._halo_t = random.uniform(96, 128)
                self._mouth_target = 0.0
                self._mouth_frame = 0
            elif self.muted:
                self._halo_t = random.uniform(22, 36)
                self._mouth_target = 0.0
                self._mouth_frame = 0
            else:
                self._halo_t = random.uniform(65, 102)
                self._mouth_target = 0.0
                self._mouth_frame = 0
            self._last_voice = now

        self._halo += (self._halo_t - self._halo) * 0.085
        self._mouth_open += (self._mouth_target - self._mouth_open) * (0.46 if speaking else 0.18)
        if not speaking and self._mouth_open < 0.04:
            self._mouth_open = 0.0
            self._mouth_frame = 0

        # Breathing stays subtle; glow carries most of the movement.
        self._breath = math.sin(self._tick * 0.008) * 0.28
        self._glow_phase = (self._glow_phase + (0.09 if speaking else 0.035)) % (math.pi * 2)

        # Eye tracking: small, non-cartoon focus motion.
        self._next_eye -= 1
        if self._next_eye <= 0:
            if self.state in ("THINKING", "PENSANDO", "PROCESANDO"):
                self._eye_dx_t = random.choice([-3.0, -2.2, 2.2, 3.0])
                self._eye_dy_t = random.uniform(-0.7, 0.9)
                self._next_eye = random.randint(85, 155)
            elif speaking:
                self._eye_dx_t = random.uniform(-1.7, 1.7)
                self._eye_dy_t = random.uniform(-0.55, 0.55)
                self._next_eye = random.randint(45, 105)
            else:
                self._eye_dx_t = random.uniform(-1.15, 1.15)
                self._eye_dy_t = random.uniform(-0.45, 0.45)
                self._next_eye = random.randint(95, 230)
        self._eye_dx += (self._eye_dx_t - self._eye_dx) * 0.06
        self._eye_dy += (self._eye_dy_t - self._eye_dy) * 0.06

        # Natural blinking, with occasional double-blink.
        self._next_blink -= 1
        if self._next_blink <= 0 and self._blink_target == 0.0:
            self._blink_target = 1.0
            self._double_blink = random.random() < 0.16
            self._next_blink = random.randint(95, 220) if not speaking else random.randint(65, 160)
        self._blink += (self._blink_target - self._blink) * 0.55
        if self._blink_target == 1.0 and self._blink > 0.88:
            self._blink_target = 0.0
            if self._double_blink:
                self._double_blink = False
                self._next_blink = random.randint(10, 24)
        if self._blink_target == 0.0 and self._blink < 0.025:
            self._blink = 0.0

        # HUD ring motion.
        ring_speed = [0.34, -0.18, 0.25, -0.42]
        if speaking:
            ring_speed = [1.15, -0.75, 1.6, -1.2]
        elif self.state in ("THINKING", "PENSANDO", "PROCESANDO"):
            ring_speed = [0.75, -0.48, 0.92, -0.70]
        for i in range(len(self._rings)):
            self._rings[i] = (self._rings[i] + ring_speed[i]) % 360

        fw = min(self.width(), self.height())
        pulse_spd = 3.8 if speaking else 1.2
        self._pulses = [r + pulse_spd for r in self._pulses if r + pulse_spd < fw * 1.16]
        if len(self._pulses) < 4 and random.random() < (0.055 if speaking else 0.014):
            self._pulses.append(0.0)

        # Particles and fairy-like digital fog.
        if random.random() < (0.28 if speaking else 0.09):
            W, H = self.width(), self.height()
            self._particles.append([
                random.uniform(W * 0.08, W * 0.94), random.uniform(H * 0.10, H * 0.92),
                random.uniform(-0.28, 0.28), random.uniform(-0.78, -0.12),
                1.0, random.choice([0, 0, 1, 2])
            ])
        self._particles = [[x+vx, y+vy, vx*0.99, vy*0.99, life-0.011, k]
                           for x,y,vx,vy,life,k in self._particles if life > 0]

        if len(self._fog) < 38 and random.random() < 0.20:
            W, H = self.width(), self.height()
            self._fog.append([
                random.uniform(W*0.05, W*0.95), random.uniform(H*0.57, H*0.98),
                random.uniform(-0.12, 0.12), random.uniform(-0.20, -0.04),
                random.uniform(0.25, 0.68), random.uniform(70, 150)
            ])
        self._fog = [[x+vx, y+vy, vx, vy, life-0.0022, rad]
                     for x,y,vx,vy,life,rad in self._fog if life > 0]

        # V37 Auto gesture decision
        self._maybe_trigger_v37_auto_gesture(speaking)

        # V37 Articulated Rig movement
        if self._v37_ready:
            self._gesture_timer += 1
            speaking = self.speaking and not self.muted

            # Get motion limits from rig_meta or defaults
            head_limit = self._v37_motion_limits.get("head", 2.4)
            upper_arm_limit = self._v37_motion_limits.get("upper_arm", 3.5)
            forearm_limit = self._v37_motion_limits.get("forearm", 4.8)
            hand_limit = self._v37_motion_limits.get("hand", 3.5)

            if speaking:
                # Head movement: smooth tilt within limits
                if self._gesture_timer % 50 == 0:
                    self._head_angle_t = random.uniform(-head_limit, head_limit)
                # Arm gestures: subtle movement
                if self._gesture_timer % 65 == 0:
                    self._left_upper_angle_t = random.uniform(-upper_arm_limit, upper_arm_limit)
                    self._right_upper_angle_t = random.uniform(-upper_arm_limit, upper_arm_limit)
                # Forearm movement
                if self._gesture_timer % 60 == 0:
                    self._left_forearm_angle_t = random.uniform(-forearm_limit, forearm_limit)
                    self._right_forearm_angle_t = random.uniform(-forearm_limit, forearm_limit)
                # Hand micro rotation
                if self._gesture_timer % 55 == 0:
                    self._left_hand_angle_t = random.uniform(-hand_limit, hand_limit)
                    self._right_hand_angle_t = random.uniform(-hand_limit, hand_limit)
            elif self.state in ("THINKING", "PENSANDO", "PROCESANDO"):
                # Slight head tilt when thinking
                if self._gesture_timer % 90 == 0:
                    self._head_angle_t = random.uniform(-head_limit * 0.5, head_limit * 0.5)
                # Arms nearly still
                self._left_upper_angle_t = 0.0
                self._right_upper_angle_t = 0.0
                self._left_forearm_angle_t = 0.0
                self._right_forearm_angle_t = 0.0
                self._left_hand_angle_t = 0.0
                self._right_hand_angle_t = 0.0
            elif self.muted:
                # Reduce movement when muted
                self._head_angle_t *= 0.3
                self._left_upper_angle_t *= 0.2
                self._right_upper_angle_t *= 0.2
                self._left_forearm_angle_t *= 0.2
                self._right_forearm_angle_t *= 0.2
                self._left_hand_angle_t *= 0.2
                self._right_hand_angle_t *= 0.2
            else:
                # Idle smooth movement
                if self._gesture_timer % 100 == 0:
                    self._head_angle_t = random.uniform(-head_limit * 0.4, head_limit * 0.4)
                if self._gesture_timer % 130 == 0:
                    self._left_upper_angle_t = random.uniform(-upper_arm_limit * 0.3, upper_arm_limit * 0.3)
                    self._right_upper_angle_t = random.uniform(-upper_arm_limit * 0.3, upper_arm_limit * 0.3)
                if self._gesture_timer % 120 == 0:
                    self._left_forearm_angle_t = random.uniform(-forearm_limit * 0.4, forearm_limit * 0.4)
                    self._right_forearm_angle_t = random.uniform(-forearm_limit * 0.4, forearm_limit * 0.4)
                if self._gesture_timer % 110 == 0:
                    self._left_hand_angle_t = random.uniform(-hand_limit * 0.3, hand_limit * 0.3)
                    self._right_hand_angle_t = random.uniform(-hand_limit * 0.3, hand_limit * 0.3)

            # Smoother easing: head interpolates slowly, arms medium, hands micro
            self._head_angle += (self._head_angle_t - self._head_angle) * 0.05
            self._left_upper_angle += (self._left_upper_angle_t - self._left_upper_angle) * 0.04
            self._right_upper_angle += (self._right_upper_angle_t - self._right_upper_angle) * 0.04
            self._left_forearm_angle += (self._left_forearm_angle_t - self._left_forearm_angle) * 0.05
            self._right_forearm_angle += (self._right_forearm_angle_t - self._right_forearm_angle) * 0.05
            self._left_hand_angle += (self._left_hand_angle_t - self._left_hand_angle) * 0.04
            self._right_hand_angle += (self._right_hand_angle_t - self._right_hand_angle) * 0.04

        # Auto gestures with cooldown
        if self._v37_ready and self._v37_auto_gestures_enabled:
            now = time.time()
            current_state = self.state

            # Only trigger auto gestures if no active gesture or gesture strength is low
            if self._v37_current_gesture is None or self._v37_gesture_strength < 0.08:
                # State changed or cooldown expired
                if current_state != self._v37_last_state_for_gesture or now - self._v37_last_auto_gesture > 18.0:
                    if current_state in ("THINKING", "PENSANDO", "PROCESANDO"):
                        if now - self._v37_last_auto_gesture > 12.0:
                            self._trigger_v37_gesture("pensando", source="auto", force=False)
                            self._v37_last_auto_gesture = now
                    elif current_state in ("LISTENING", "READY", "ACTIVE"):
                        if now - self._v37_last_auto_gesture > 20.0 and random.random() < 0.3:
                            self._trigger_v37_gesture("escuchando", source="auto", force=False)
                            self._v37_last_auto_gesture = now
                    elif speaking:
                        if now - self._v37_last_auto_gesture > 18.0 and random.random() < 0.25:
                            self._trigger_v37_gesture("presentando", source="auto", force=False)
                            self._v37_last_auto_gesture = now

            self._v37_last_state_for_gesture = current_state

        # Update gesture
        self._update_v37_gesture()

        # Calculate final angles with gesture offsets using per-layer strength
        m = self._v37_gesture_intensity_multiplier
        targets = self._v37_gesture_targets or {}
        offsets = self._v37_gesture_offsets or {}

        # Use per-layer strength for natural stagger
        g_head = self._gesture_layer_strength("head")
        g_left_upper = self._gesture_layer_strength("left_upper_arm")
        g_left_forearm = self._gesture_layer_strength("left_forearm")
        g_left_hand = self._gesture_layer_strength("left_hand")
        g_right_upper = self._gesture_layer_strength("right_upper_arm")
        g_right_forearm = self._gesture_layer_strength("right_forearm")
        g_right_hand = self._gesture_layer_strength("right_hand")

        self._head_angle_final = self._head_angle + float(targets.get("head", 0.0)) * g_head * m
        self._left_upper_angle_final = self._left_upper_angle + float(targets.get("left_upper_arm", 0.0)) * g_left_upper * m
        self._left_forearm_angle_final = self._left_forearm_angle + float(targets.get("left_forearm", 0.0)) * g_left_forearm * m
        self._left_hand_angle_final = self._left_hand_angle + float(targets.get("left_hand", 0.0)) * g_left_hand * m
        self._right_upper_angle_final = self._right_upper_angle + float(targets.get("right_upper_arm", 0.0)) * g_right_upper * m
        self._right_forearm_angle_final = self._right_forearm_angle + float(targets.get("right_forearm", 0.0)) * g_right_forearm * m
        self._right_hand_angle_final = self._right_hand_angle + float(targets.get("right_hand", 0.0)) * g_right_hand * m

        # Calculate final offsets with gesture offsets using per-layer strength
        self._head_dx_final = self._head_dx + float(offsets.get("head", [0, 0])[0]) * g_head
        self._head_dy_final = self._head_dy + float(offsets.get("head", [0, 0])[1]) * g_head
        self._left_upper_dx_final = float(offsets.get("left_upper_arm", [0, 0])[0]) * g_left_upper
        self._left_upper_dy_final = float(offsets.get("left_upper_arm", [0, 0])[1]) * g_left_upper
        self._left_forearm_dx_final = float(offsets.get("left_forearm", [0, 0])[0]) * g_left_forearm
        self._left_forearm_dy_final = float(offsets.get("left_forearm", [0, 0])[1]) * g_left_forearm
        self._left_hand_dx_final = float(offsets.get("left_hand", [0, 0])[0]) * g_left_hand
        self._left_hand_dy_final = float(offsets.get("left_hand", [0, 0])[1]) * g_left_hand
        self._right_upper_dx_final = float(offsets.get("right_upper_arm", [0, 0])[0]) * g_right_upper
        self._right_upper_dy_final = float(offsets.get("right_upper_arm", [0, 0])[1]) * g_right_upper
        self._right_forearm_dx_final = float(offsets.get("right_forearm", [0, 0])[0]) * g_right_forearm
        self._right_forearm_dy_final = float(offsets.get("right_forearm", [0, 0])[1]) * g_right_forearm
        self._right_hand_dx_final = float(offsets.get("right_hand", [0, 0])[0]) * g_right_hand
        self._right_hand_dy_final = float(offsets.get("right_hand", [0, 0])[1]) * g_right_hand

        # Apply oscillations
        if self._v37_current_gesture and self._v37_gesture_oscillations:
            elapsed = time.time() - self._v37_gesture_started_at
            for layer_name, osc in self._v37_gesture_oscillations.items():
                if isinstance(osc, dict):
                    start = osc.get("start", 0.0)
                    end = osc.get("end", 999.0)
                    if start <= elapsed <= end:
                        amp = float(osc.get("angle_amplitude", 0.0))
                        freq = float(osc.get("frequency", 4.0))
                        wave = math.sin(elapsed * math.pi * 2.0 * freq) * amp
                        if layer_name == "head":
                            self._head_angle_final += wave
                        elif layer_name == "left_upper_arm":
                            self._left_upper_angle_final += wave
                        elif layer_name == "left_forearm":
                            self._left_forearm_angle_final += wave
                        elif layer_name == "left_hand":
                            self._left_hand_angle_final += wave
                        elif layer_name == "right_upper_arm":
                            self._right_upper_angle_final += wave
                        elif layer_name == "right_forearm":
                            self._right_forearm_angle_final += wave
                        elif layer_name == "right_hand":
                            self._right_hand_angle_final += wave

        self.update()

    def _model_to_view(self, rect: QRectF) -> QRectF:
        if self._model_rect.isNull():
            return QRectF()
        sx = self._model_rect.width() / self._model_size.width()
        sy = self._model_rect.height() / self._model_size.height()
        return QRectF(
            self._model_rect.x() + rect.x() * sx,
            self._model_rect.y() + rect.y() * sy,
            rect.width() * sx,
            rect.height() * sy,
        )

    def _draw_background(self, p: QPainter, W: int, H: int):
        p.fillRect(self.rect(), qcol(C.BG))
        # Deep radial aura.
        center = QPointF(W * 0.48, H * 0.50)
        grad = QRadialGradient(center, min(W, H) * 0.86)
        grad.setColorAt(0.00, qcol("#062a48", 190))
        grad.setColorAt(0.38, qcol("#05101f", 230))
        grad.setColorAt(1.00, qcol(C.BG, 255))
        p.setBrush(QBrush(grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(0, 0, W, H))
        # Subtle grid.
        p.setPen(QPen(qcol(C.PRI, 18), 1))
        for x in range(0, W, 44):
            p.drawLine(QPointF(x, 0), QPointF(x, H))
        for y in range(0, H, 44):
            p.drawLine(QPointF(0, y), QPointF(W, y))

    def _draw_rings(self, p: QPainter, W: int, H: int):
        cx, cy = W * 0.51, H * 0.47
        fw = min(W, H)
        for pr in self._pulses:
            a = max(0, int(70 * (1.0 - pr / (fw * 1.16))))
            p.setPen(QPen(qcol(C.PRI, a), 1.0))
            p.drawEllipse(QRectF(cx-pr, cy-pr, pr*2, pr*2))
        configs = [(0.51, 68, 82, 1.45, C.PRI), (0.41, 48, 72, 1.05, "#8ad7ff"), (0.31, 36, 80, 0.90, "#9a4dff"), (0.57, 22, 96, 0.75, C.PRI)]
        for idx, (rf, alen, gap, width, col) in enumerate(configs):
            rr = fw * rf
            rect = QRectF(cx-rr, cy-rr, rr*2, rr*2)
            p.setPen(QPen(qcol(col, 74 if idx < 2 else 48), width))
            a = self._rings[idx]
            while a < self._rings[idx] + 360:
                p.drawArc(rect, int(a*16), int(alen*16))
                a += alen + gap

    def _draw_fog(self, p: QPainter):
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, _vx, _vy, life, rad in self._fog:
            grad = QRadialGradient(QPointF(x, y), rad)
            a = int(42 * life)
            grad.setColorAt(0.0, qcol("#8ad7ff", a))
            grad.setColorAt(0.38, qcol("#b243ff", max(0, a//2)))
            grad.setColorAt(1.0, qcol(C.BG, 0))
            p.setBrush(QBrush(grad))
            p.drawEllipse(QRectF(x-rad, y-rad*0.34, rad*2, rad*0.68))

    def _draw_model_and_rig(self, p: QPainter, W: int, H: int):
        if self._v37_ready:
            self._draw_v37_model_and_rig(p, W, H)
            return

        if not self._model_px:
            p.setPen(QPen(qcol(C.PRI, 200), 1))
            p.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
            p.drawText(QRectF(0, H*0.42, W, 80), Qt.AlignmentFlag.AlignCenter, "HELENA")
            return

        # Scale like the target concept: portrait bust dominates the core page.
        max_h = int(H * 0.94)
        max_w = int(W * 0.58)
        scaled = self._model_px.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        x = int(W * 0.49 - scaled.width() / 2)
        y = int(H * 0.51 - scaled.height() / 2 + self._breath)
        self._model_rect = QRectF(x, y, scaled.width(), scaled.height())
        self._model_size = self._model_px.size()

        # Back glow, then silhouette glow, then crisp model.
        glow_rad = min(W, H) * (0.45 + 0.025 * math.sin(self._glow_phase))
        glow = QRadialGradient(QPointF(W*0.50, H*0.52), glow_rad)
        glow.setColorAt(0.0, qcol("#a547ff", int(self._halo*0.20)))
        glow.setColorAt(0.32, qcol(C.PRI, int(self._halo*0.25)))
        glow.setColorAt(1.0, qcol(C.BG, 0))
        p.setBrush(QBrush(glow)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(W*0.50-glow_rad, H*0.52-glow_rad, glow_rad*2, glow_rad*2))

        p.setOpacity(0.22)
        p.drawPixmap(x-4, y+2, scaled)
        p.setOpacity(0.97 if not self.muted else 0.52)
        p.drawPixmap(x, y, scaled)
        p.setOpacity(1.0)

        self._draw_facial_layers(p)

    def _draw_sprite(self, p: QPainter, key: str, target: QRectF, opacity: float = 1.0, dx: float = 0.0, dy: float = 0.0, scale_y: float = 1.0):
        px = self._sprites.get(key)
        if not px or target.isNull():
            return
        r = QRectF(target)
        r.translate(dx, dy)
        if abs(scale_y - 1.0) > 0.01:
            center = r.center()
            r.setHeight(r.height() * scale_y)
            r.moveCenter(center)
        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawPixmap(r, px, QRectF(px.rect()))
        p.restore()

    def _draw_facial_layers(self, p: QPainter):
        """Draw full-canvas facial sprites.

        V6.4 uses usuario's manual Photoshop sprites.  They are NOT tiny cropped
        pieces anymore: each sprite has the exact same canvas size as
        model_core.png.  The painter simply draws the sprite over the same
        model rectangle, which keeps mouth and eyelids locked to Helena.
        """
        if self._model_rect.isNull():
            return

        blink = max(0.0, min(1.0, self._blink))

        # Subtle open-eye sheen. The base model already has open eyes, so this
        # is intentionally very low opacity to avoid a pasted/double-eye look.
        if blink < 0.08:
            self._draw_sprite(p, "eyes_open", self._model_rect, 0.045)
        else:
            # Use a half-closed frame during the travel, then the darker closed
            # frame for the peak of the blink.  This makes blink readable but
            # avoids the old one-frame black patch.
            half_op = max(0.0, min(1.0, (1.0 - abs(blink - 0.45) / 0.45))) * 0.72
            closed_op = max(0.0, (blink - 0.42) / 0.58)
            if half_op > 0.02:
                self._draw_sprite(p, "eyes_half", self._model_rect, half_op)
            if closed_op > 0.02:
                self._draw_sprite(p, "eyes_closed", self._model_rect, min(1.0, closed_op * 1.12))

        # Speaking.  Mouth sprites are also full-canvas.  No procedural black
        # ellipse is drawn anymore; the depth comes from the Photoshop mouth frames.
        if self._mouth_open > 0.020:
            frame = max(1, min(4, self._mouth_frame))
            # A small opacity pulse gives life without changing alignment.
            op = 0.72 + 0.24 * max(0.0, min(1.0, self._mouth_open))
            self._draw_sprite(p, f"mouth_{frame}", self._model_rect, op)
        elif self.state in ("LISTENING", "ACTIVE", "READY"):
            # Very faint closed-mouth layer to keep exact visual continuity with
            # the manual sprite set; almost invisible over the base model.
            self._draw_sprite(p, "mouth_0", self._model_rect, 0.035)

    def _draw_v37_layer(self, p: QPainter, key: str, opacity: float = 1.0):
        px = self._v37_layers.get(key)
        if not px or self._model_rect.isNull():
            return
        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawPixmap(self._model_rect, px, QRectF(px.rect()))
        p.restore()

    def _draw_v37_layer_pivoted(self, p: QPainter, key: str, pivot_local: tuple, angle_deg: float = 0.0, opacity: float = 1.0, dx: float = 0.0, dy: float = 0.0):
        px = self._v37_layers.get(key)
        if not px or self._model_rect.isNull():
            return

        sx = self._model_rect.width() / 1149.0
        sy = self._model_rect.height() / 1369.0

        pivot_view = QPointF(
            self._model_rect.x() + pivot_local[0] * sx + dx,
            self._model_rect.y() + pivot_local[1] * sy + dy
        )

        r = QRectF(self._model_rect)
        r.translate(dx, dy)

        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.translate(pivot_view)
        p.rotate(angle_deg)
        p.translate(-pivot_view)
        p.drawPixmap(r, px, QRectF(px.rect()))
        p.restore()

    def _v37_local_to_view(self, point):
        """Transform local coordinates to view coordinates."""
        sx = self._model_rect.width() / 1149.0
        sy = self._model_rect.height() / 1369.0
        return QPointF(
            self._model_rect.x() + point[0] * sx,
            self._model_rect.y() + point[1] * sy
        )

    def _draw_v37_layer_chain(self, p, key, transforms, opacity=1.0):
        """Draw a layer with hierarchical chain of transformations."""
        px = self._v37_layers.get(key)
        if not px or self._model_rect.isNull():
            return

        p.save()
        p.setOpacity(max(0.0, min(1.0, opacity)))

        for pivot_local, angle_deg, dx, dy in transforms:
            pivot = self._v37_local_to_view(pivot_local)
            pivot.setX(pivot.x() + dx)
            pivot.setY(pivot.y() + dy)
            p.translate(pivot)
            p.rotate(angle_deg)
            p.translate(-pivot)

        p.drawPixmap(self._model_rect, px, QRectF(px.rect()))
        p.restore()

    def _draw_v37_model_and_rig(self, p: QPainter, W: int, H: int):
        preview_full = self._v37_layers.get("preview_full")
        if not preview_full:
            return

        # Scale using preview_full as reference
        max_h = int(H * 0.94)
        max_w = int(W * 0.58)
        scaled = preview_full.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        x = int(W * 0.49 - scaled.width() / 2)
        y = int(H * 0.51 - scaled.height() / 2 + self._breath)
        self._model_rect = QRectF(x, y, scaled.width(), scaled.height())
        self._model_size = preview_full.size()

        # Back glow
        glow_rad = min(W, H) * (0.45 + 0.025 * math.sin(self._glow_phase))
        glow = QRadialGradient(QPointF(W*0.50, H*0.52), glow_rad)
        glow.setColorAt(0.0, qcol("#a547ff", int(self._halo*0.20)))
        glow.setColorAt(0.32, qcol(C.PRI, int(self._halo*0.25)))
        glow.setColorAt(1.0, qcol(C.BG, 0))
        p.setBrush(QBrush(glow)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(W*0.50-glow_rad, H*0.52-glow_rad, glow_rad*2, glow_rad*2))

        # Draw layers in order
        head_pivot = self._v37_pivots.get("head", (605, 405))
        left_upper_pivot = self._v37_pivots.get("left_upper_arm", (780, 500))
        left_forearm_pivot = self._v37_pivots.get("left_forearm", (815, 830))
        left_hand_pivot = self._v37_pivots.get("left_hand", (940, 1070))
        right_upper_pivot = self._v37_pivots.get("right_upper_arm", (400, 470))
        right_forearm_pivot = self._v37_pivots.get("right_forearm", (350, 725))
        right_hand_pivot = self._v37_pivots.get("right_hand", (200, 1080))

        # 1. hair_back, pivoted with head_angle_final * 0.35
        self._draw_v37_layer_pivoted(p, "hair_back", head_pivot, self._head_angle_final * 0.35)

        # 2. neck, normal if exists
        if "neck" in self._v37_layers:
            self._draw_v37_layer(p, "neck")

        # 3. body_base
        self._draw_v37_layer(p, "body_base")

        # 4-9. Arms - use hierarchical or simple mode
        if self._v37_arm_rig_mode == "hierarchical":
            # Right arm chain
            right_shoulder = right_upper_pivot
            right_elbow = right_forearm_pivot
            right_wrist = right_hand_pivot

            # right_upper_arm: shoulder only
            self._draw_v37_layer_chain(p, "right_upper_arm", [
                (right_shoulder, self._right_upper_angle_final, self._right_upper_dx_final, self._right_upper_dy_final)
            ])

            # left_upper_arm: shoulder only
            self._draw_v37_layer_chain(p, "left_upper_arm", [
                (left_upper_pivot, self._left_upper_angle_final, self._left_upper_dx_final, self._left_upper_dy_final)
            ])

            # right_forearm: shoulder + elbow
            self._draw_v37_layer_chain(p, "right_forearm", [
                (right_shoulder, self._right_upper_angle_final, self._right_upper_dx_final, self._right_upper_dy_final),
                (right_elbow, self._right_forearm_angle_final, self._right_forearm_dx_final, self._right_forearm_dy_final)
            ])

            # left_forearm: shoulder + elbow
            self._draw_v37_layer_chain(p, "left_forearm", [
                (left_upper_pivot, self._left_upper_angle_final, self._left_upper_dx_final, self._left_upper_dy_final),
                (left_forearm_pivot, self._left_forearm_angle_final, self._left_forearm_dx_final, self._left_forearm_dy_final)
            ])

            # right_hand: shoulder + elbow + wrist
            self._draw_v37_layer_chain(p, "right_hand", [
                (right_shoulder, self._right_upper_angle_final, self._right_upper_dx_final, self._right_upper_dy_final),
                (right_elbow, self._right_forearm_angle_final, self._right_forearm_dx_final, self._right_forearm_dy_final),
                (right_wrist, self._right_hand_angle_final, self._right_hand_dx_final, self._right_hand_dy_final)
            ])

            # left_hand: shoulder + elbow + wrist
            self._draw_v37_layer_chain(p, "left_hand", [
                (left_upper_pivot, self._left_upper_angle_final, self._left_upper_dx_final, self._left_upper_dy_final),
                (left_forearm_pivot, self._left_forearm_angle_final, self._left_forearm_dx_final, self._left_forearm_dy_final),
                (left_hand_pivot, self._left_hand_angle_final, self._left_hand_dx_final, self._left_hand_dy_final)
            ])
        else:
            # Simple mode - independent pivots
            # 4. right_upper_arm, pivoted
            self._draw_v37_layer_pivoted(p, "right_upper_arm", right_upper_pivot, self._right_upper_angle_final)

            # 5. left_upper_arm, pivoted
            self._draw_v37_layer_pivoted(p, "left_upper_arm", left_upper_pivot, self._left_upper_angle_final)

            # 6. right_forearm, pivoted
            self._draw_v37_layer_pivoted(p, "right_forearm", right_forearm_pivot, self._right_forearm_angle_final)

            # 7. left_forearm, pivoted
            self._draw_v37_layer_pivoted(p, "left_forearm", left_forearm_pivot, self._left_forearm_angle_final)

            # 8. right_hand, pivoted
            self._draw_v37_layer_pivoted(p, "right_hand", right_hand_pivot, self._right_hand_angle_final)

            # 9. left_hand, pivoted
            self._draw_v37_layer_pivoted(p, "left_hand", left_hand_pivot, self._left_hand_angle_final)

        # 10. skirt_clothes_front if exists
        if "skirt_clothes_front" in self._v37_layers:
            self._draw_v37_layer(p, "skirt_clothes_front")

        # 11. dress_top_front if exists
        if "dress_top_front" in self._v37_layers:
            self._draw_v37_layer(p, "dress_top_front")

        # 12. head, pivoted with head_angle_final, head_dx, head_dy
        self._draw_v37_layer_pivoted(p, "head", head_pivot, self._head_angle_final, 1.0, self._head_dx, self._head_dy)

        # 13. eyes and mouth using _draw_v37_facial_layers (must follow head pivot)
        self._draw_v37_facial_layers(p)

        # 14. hair_front, pivoted with head_angle_final (drawn last to be on top)
        self._draw_v37_layer_pivoted(p, "hair_front", head_pivot, self._head_angle_final)

        # Debug drawing
        if self._v37_debug_show_pivots:
            self._draw_debug_pivots(p)
        if self._v37_debug_show_model_rect:
            self._draw_debug_model_rect(p)
        if self._v37_debug_show_layer_bounds:
            self._draw_debug_layer_bounds(p)
        if self._v37_debug_show_transformed_pivots and self._v37_arm_rig_mode == "hierarchical":
            self._draw_debug_transformed_pivots(p)
        if self._v37_debug_gesture_state or self._v37_debug_show_gesture_overlay:
            self._draw_gesture_debug_overlay(p)

    def _draw_debug_pivots(self, p: QPainter):
        """Draw pivot points for debugging."""
        if self._model_rect.isNull():
            return

        sx = self._model_rect.width() / 1149.0
        sy = self._model_rect.height() / 1369.0

        p.save()
        p.setPen(QPen(qcol("#ff00ff", 200), 2))
        p.setBrush(QBrush(qcol("#ff00ff", 150)))
        p.setFont(QFont("Courier New", 8))

        for pivot_name, pivot_local in self._v37_pivots.items():
            pivot_view = QPointF(
                self._model_rect.x() + pivot_local[0] * sx,
                self._model_rect.y() + pivot_local[1] * sy
            )
            p.drawEllipse(pivot_view, 4, 4)
            p.drawText(QPointF(pivot_view.x() + 8, pivot_view.y() - 8), pivot_name)

        p.restore()

    def _draw_debug_model_rect(self, p: QPainter):
        """Draw the model rectangle for debugging."""
        if self._model_rect.isNull():
            return

        p.save()
        p.setPen(QPen(qcol("#00ff00", 200), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(self._model_rect))
        p.restore()

    def _draw_debug_layer_bounds(self, p: QPainter):
        """Draw bounding boxes of V37 layers for debugging."""
        if self._model_rect.isNull():
            return

        p.save()
        p.setPen(QPen(qcol("#ffff00", 150), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)

        for key in self._v37_layers:
            px = self._v37_layers.get(key)
            if not px or px.isNull():
                continue
            rect = QRectF(px.rect())
            p.drawRect(QRectF(self._model_rect.x(), self._model_rect.y(), rect.width() * (self._model_rect.width() / 1149.0), rect.height() * (self._model_rect.height() / 1369.0)))

        p.restore()

    def _draw_debug_transformed_pivots(self, p: QPainter):
        """Draw transformed pivot points for hierarchical arm rig debugging."""
        if self._model_rect.isNull():
            return

        p.save()
        p.setPen(QPen(qcol("#00ffff", 200), 2))
        p.setBrush(QBrush(qcol("#00ffff", 180)))

        # Get arm pivots
        right_upper_pivot = self._v37_pivots.get("right_upper_arm", (400, 470))
        right_forearm_pivot = self._v37_pivots.get("right_forearm", (350, 725))
        right_hand_pivot = self._v37_pivots.get("right_hand", (200, 1080))
        left_upper_pivot = self._v37_pivots.get("left_upper_arm", (780, 500))
        left_forearm_pivot = self._v37_pivots.get("left_forearm", (815, 830))
        left_hand_pivot = self._v37_pivots.get("left_hand", (940, 1070))

        # Calculate transformed pivots for right arm
        right_shoulder = self._v37_local_to_view(right_upper_pivot)
        right_shoulder.setX(right_shoulder.x() + self._right_upper_dx_final)
        right_shoulder.setY(right_shoulder.y() + self._right_upper_dy_final)

        right_elbow = self._v37_local_to_view(right_forearm_pivot)
        right_elbow.setX(right_elbow.x() + self._right_forearm_dx_final)
        right_elbow.setY(right_elbow.y() + self._right_forearm_dy_final)

        right_wrist = self._v37_local_to_view(right_hand_pivot)
        right_wrist.setX(right_wrist.x() + self._right_hand_dx_final)
        right_wrist.setY(right_wrist.y() + self._right_hand_dy_final)

        # Calculate transformed pivots for left arm
        left_shoulder = self._v37_local_to_view(left_upper_pivot)
        left_shoulder.setX(left_shoulder.x() + self._left_upper_dx_final)
        left_shoulder.setY(left_shoulder.y() + self._left_upper_dy_final)

        left_elbow = self._v37_local_to_view(left_forearm_pivot)
        left_elbow.setX(left_elbow.x() + self._left_forearm_dx_final)
        left_elbow.setY(left_elbow.y() + self._left_forearm_dy_final)

        left_wrist = self._v37_local_to_view(left_hand_pivot)
        left_wrist.setX(left_wrist.x() + self._left_hand_dx_final)
        left_wrist.setY(left_wrist.y() + self._left_hand_dy_final)

        # Draw cyan circles for transformed pivots
        for pivot in [right_shoulder, right_elbow, right_wrist, left_shoulder, left_elbow, left_wrist]:
            p.drawEllipse(pivot, 4, 4)

        p.restore()

    def _draw_gesture_debug_overlay(self, p: QPainter):
        """Draw gesture debug overlay showing current gesture state and render angles."""
        if not self._v37_ready or self._model_rect.isNull():
            return
        if not self._v37_debug_show_gesture_overlay:
            return

        render_angles = self._v37_get_render_angles()

        p.save()
        p.setPen(QPen(qcol("#00ff00", 120), 1))
        p.setBrush(QBrush(qcol("#001100", 100)))
        
        # Draw overlay box at bottom status area (decorative HUD area)
        W = self.width()
        H = self.height()
        overlay_rect = QRectF(W * 0.30, H * 0.87, W * 0.34, 45)
        p.drawRoundedRect(overlay_rect, 3, 3)
        
        # Draw text
        p.setFont(QFont("Courier New", 7))
        p.setPen(qcol("#00ff00", 180))
        
        if self._v37_current_gesture:
            variant_str = f" / {self._v37_current_gesture_variant}" if self._v37_current_gesture_variant else ""
            text = f"GESTURE: {self._v37_current_gesture}{variant_str} source={self._v37_gesture_source} strength={self._v37_gesture_strength:.2f}"
            draw_head = f"HEAD={render_angles['head']:.1f}"
            draw_lu = f"LU={render_angles['left_upper_arm']:.1f}"
            draw_lf = f"LF={render_angles['left_forearm']:.1f}"
            draw_lh = f"LH={render_angles['left_hand']:.1f}"
            draw_ru = f"RU={render_angles['right_upper_arm']:.1f}"
            draw_rf = f"RF={render_angles['right_forearm']:.1f}"
            draw_rh = f"RH={render_angles['right_hand']:.1f}"
            
            p.drawText(overlay_rect.adjusted(8, 4, -6, -6), text)
            p.drawText(overlay_rect.adjusted(8, 16, -6, -6), f"{draw_head} {draw_lu} {draw_lf} {draw_lh}")
            p.drawText(overlay_rect.adjusted(8, 28, -6, -6), f"{draw_ru} {draw_rf} {draw_rh}")
        else:
            p.drawText(overlay_rect.adjusted(8, 4, -6, -6), "GESTURE: None")
            p.drawText(overlay_rect.adjusted(8, 16, -6, -6), f"strength={self._v37_gesture_strength:.2f}")
        
        p.restore()

    def _draw_v37_facial_layers(self, p: QPainter):
        if self._model_rect.isNull():
            return

        head_pivot = self._v37_pivots.get("head", (605, 405))
        blink = max(0.0, min(1.0, self._blink))

        # Eyes with head pivot
        if blink < 0.08:
            self._draw_v37_layer_pivoted(p, "eyes_open", head_pivot, self._head_angle_final, 0.045)
        else:
            half_op = max(0.0, min(1.0, (1.0 - abs(blink - 0.45) / 0.45))) * 0.72
            closed_op = max(0.0, (blink - 0.42) / 0.58)
            if half_op > 0.02:
                self._draw_v37_layer_pivoted(p, "eyes_half", head_pivot, self._head_angle_final, half_op)
            if closed_op > 0.02:
                self._draw_v37_layer_pivoted(p, "eyes_closed", head_pivot, self._head_angle_final, min(1.0, closed_op * 1.12))

        # Apply gesture expression (eyes_half_opacity) on top of normal blink
        if self._v37_ready and self._v37_gesture_expression:
            eyes_half_opacity = self._v37_gesture_expression.get("eyes_half_opacity", 0.0)
            if eyes_half_opacity > 0.0:
                gesture_half_op = max(0.0, min(1.0, eyes_half_opacity))
                self._draw_v37_layer_pivoted(p, "eyes_half", head_pivot, self._head_angle_final, gesture_half_op)

        # Mouth with head pivot
        if self._mouth_open > 0.020:
            frame = max(1, min(4, self._mouth_frame))
            op = 0.72 + 0.24 * max(0.0, min(1.0, self._mouth_open))
            self._draw_v37_layer_pivoted(p, f"mouth_{frame}", head_pivot, self._head_angle_final, op)
        elif self.state in ("LISTENING", "ACTIVE", "READY"):
            self._draw_v37_layer_pivoted(p, "mouth_0", head_pivot, self._head_angle_final, 0.035)

    def _draw_status_overlays(self, p: QPainter, W: int, H: int):
        # Left small status.
        panel = QRectF(W*0.045, H*0.34, 138, 94)
        p.setPen(QPen(qcol(C.PRI, 78), 1)); p.setBrush(QBrush(qcol("#03101d", 110)))
        p.drawRoundedRect(panel, 8, 8)
        p.setFont(QFont("Courier New", 8))
        p.setPen(qcol(C.TEXT_MED, 185)); p.drawText(panel.adjusted(16, 12, -8, -8), "STATUS")
        status = "SPEAKING" if self.speaking else ("THINKING" if self.state in ("THINKING", "PENSANDO", "PROCESANDO") else "LISTENING")
        p.setFont(QFont("Courier New", 15))
        p.setPen(qcol(C.PRI if status != "SPEAKING" else "#8ad7ff", 220)); p.drawText(panel.adjusted(16, 33, -8, -8), status)
        p.setPen(QPen(qcol(C.PRI, 150), 1))
        for i in range(26):
            h = 3 + int(14*abs(math.sin(self._tick*0.08 + i*.55))) if self.speaking else 3 + int(5*abs(math.sin(self._tick*0.04 + i*.42)))
            x = panel.x()+18+i*4
            p.drawLine(QPointF(x, panel.y()+74-h/2), QPointF(x, panel.y()+74+h/2))

        # Right emotional matrix.
        ep = QRectF(W-184, H*0.25, 150, 170)
        p.setPen(QPen(qcol(C.PRI, 72), 1)); p.setBrush(QBrush(qcol("#03101d", 94)))
        p.drawRoundedRect(ep, 8, 8)
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold)); p.setPen(qcol(C.TEXT_MED, 190))
        p.drawText(ep.adjusted(14, 12, -8, -8), "EMOTIONAL MATRIX")
        vals = [("CALM", 78), ("FOCUS", 65), ("EMPATHY", 92), ("ENERGY", 48)]
        y = ep.y()+52
        for label, val in vals:
            p.setPen(qcol(C.TEXT_MED, 170)); p.drawText(QPointF(ep.x()+16, y), label)
            p.setPen(qcol(C.PRI, 185)); p.drawText(QPointF(ep.x()+108, y), f"{val}%")
            p.setPen(QPen(qcol(C.PRI, 52), 1)); p.drawLine(QPointF(ep.x()+16, y+8), QPointF(ep.x()+132, y+8))
            p.setPen(QPen(qcol(C.PRI, 160), 2)); p.drawLine(QPointF(ep.x()+16, y+8), QPointF(ep.x()+16+val*1.05, y+8))
            y += 28

        # Bottom identity wave and rig status.
        wave_y = H - 110
        p.setPen(QPen(qcol(C.PRI, 120), 1))
        for i in range(110):
            amp = 8 + (14 if self.speaking else 4) * abs(math.sin(self._tick*0.08 + i*.37))
            x = W*0.12 + i*(W*0.76/110)
            p.drawLine(QPointF(x, wave_y-amp/2), QPointF(x, wave_y+amp/2))
        p.setFont(QFont("Courier New", 20, QFont.Weight.Bold)); p.setPen(qcol(C.PRI, 215))
        p.drawText(QRectF(0, wave_y+12, W, 34), Qt.AlignmentFlag.AlignCenter, "H E L E N A")
        p.setFont(QFont("Courier New", 7)); p.setPen(qcol(C.TEXT_MED, 160))
        p.drawText(QRectF(0, wave_y+42, W, 20), Qt.AlignmentFlag.AlignCenter, "Holographic Emotional AI Assistant")

        labels = [("BLINK", f"{max(1.5, self._next_blink/60):.1f}s"), ("EYES", "FOCUS"), ("MOUTH", "SPEAKING" if self.speaking else "READY"), ("HEAD", "NATURAL"), ("BREATH", "CALM"), ("GLOW", "ACTIVE")]
        start = W*0.18; cell = W*0.11; y = H-48
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        for idx,(a,b) in enumerate(labels):
            x = start + idx*cell
            p.setPen(qcol(C.TEXT_MED, 135)); p.drawText(QRectF(x, y, cell, 16), Qt.AlignmentFlag.AlignCenter, a)
            p.setPen(qcol(C.PRI if idx != 2 else "#ff73d7", 190)); p.drawText(QRectF(x, y+18, cell, 18), Qt.AlignmentFlag.AlignCenter, b)
            if idx:
                p.setPen(QPen(qcol(C.BORDER_A, 34), 1)); p.drawLine(QPointF(x, y+2), QPointF(x, y+34))

    def paintEvent(self, _):
        W, H = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_background(p, W, H)
        self._draw_fog(p)
        self._draw_rings(p, W, H)
        self._draw_model_and_rig(p, W, H)

        # Fine scanlines, then particles.
        p.setPen(QPen(qcol(C.PRI, 14), 1))
        off = self._tick % 6
        for yy in range(off, H, 6):
            p.drawLine(QPointF(0, yy), QPointF(W, yy))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, _vx, _vy, life, kind in self._particles:
            col = C.PRI if kind == 0 else ("#8ad7ff" if kind == 1 else "#b243ff")
            p.setBrush(QBrush(qcol(col, int(185*life))))
            p.drawEllipse(QPointF(x, y), 1.5, 1.5)
        self._draw_status_overlays(p, W, H)

class VoiceWaveWidget(QWidget):
    """Small reactive audio/wave panel.

    It reacts to HELENA state now and can be wired to real microphone RMS later.
    The goal is a refined waveform, not the old blocky text bars.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(72)
        self._state = "LISTENING"
        self._levels = [0.08 for _ in range(54)]
        self._phase = 0.0
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(45)

    def set_state(self, state: str):
        self._state = state or "LISTENING"

    def _step(self):
        self._phase += 0.18
        active = self._state in ("LISTENING", "SPEAKING", "THINKING")
        amp = 0.25
        if self._state == "SPEAKING": amp = 0.82
        elif self._state == "LISTENING": amp = 0.52
        elif self._state == "THINKING": amp = 0.34
        elif self._state == "MUTED": amp = 0.08
        self._levels = self._levels[1:] + [max(0.04, min(1.0, (0.25 + 0.65*abs(math.sin(self._phase*1.7 + random.random()))) * amp if active else 0.04))]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol('#020814', 220)))
        p.drawRoundedRect(QRectF(0, 0, W, H), 6, 6)
        mid = H * 0.43
        if self._state == "MUTED": col = C.MUTED_C
        elif self._state == "SPEAKING": col = '#8ad7ff'
        elif self._state == "THINKING": col = C.ACC
        else: col = C.PRI
        # glow center line
        p.setPen(QPen(qcol(col, 38), 1))
        p.drawLine(QPointF(8, mid), QPointF(W-8, mid))
        step = (W - 20) / max(1, len(self._levels)-1)
        for i, lv in enumerate(self._levels):
            x = 10 + i * step
            h = 3 + lv * (H * 0.45)
            alpha = 70 + int(145 * lv)
            p.setPen(QPen(qcol(col, alpha), max(1.0, step*0.45)))
            p.drawLine(QPointF(x, mid-h/2), QPointF(x, mid+h/2))
        label = {
            'SPEAKING':'* SPEAKING...', 'THINKING':'* THINKING...', 'MUTED':'X MUTED',
        }.get(self._state, '* LISTENING...')
        p.setFont(QFont('Courier New', 10, QFont.Weight.Bold))
        p.setPen(qcol(col, 220))
        p.drawText(QRectF(6, H-24, W-12, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)


class CoreStatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(96)
        self.cpu = 0.0; self.temp = -1.0; self.mem = 0.0; self.uptime = '--:--'
        self.status = 'ALL SYSTEMS ONLINE'

    def update_values(self, cpu: float, mem: float, temp: float, uptime: str):
        self.cpu = cpu; self.mem = mem; self.temp = temp; self.uptime = uptime
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W,H = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(qcol('#020814', 210)))
        p.drawRoundedRect(QRectF(0, 0, W, H), 6, 6)
        if self.temp < 0:
            first_label, first_value = 'SYS', 'OK'
        else:
            first_label, first_value = 'TEMP', f'{self.temp:.0f}°C'
        vals = [
            (first_label, first_value),
            ('LOAD', f'{self.cpu:.0f}%'),
            ('RAM', f'{self.mem:.0f}%'),
            ('UPTIME', self.uptime),
        ]
        p.setFont(QFont('Courier New', 7, QFont.Weight.Bold))
        for i,(k,v) in enumerate(vals):
            col = i % 2; row = i // 2
            r = QRectF(8 + col*(W-22)/2, 8 + row*34, (W-28)/2, 29)
            p.setPen(QPen(qcol(C.BORDER_A, 75), 1))
            p.setBrush(QBrush(qcol('#041323', 150)))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(qcol(C.TEXT_MED, 180)); p.drawText(r.adjusted(7, 3, -4, -3), Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft, k)
            vcol = C.GREEN if (k == 'SYS' and v == 'OK') else (C.ACC if (k == 'TEMP' and self.temp >= 70) or (k == 'LOAD' and self.cpu >= 75) else C.PRI)
            p.setFont(QFont('Courier New', 12, QFont.Weight.Bold)); p.setPen(qcol(vcol, 230))
            p.drawText(r.adjusted(7, 11, -4, -3), Qt.AlignmentFlag.AlignBottom|Qt.AlignmentFlag.AlignLeft, v)
            p.setFont(QFont('Courier New', 7, QFont.Weight.Bold))
        p.setPen(qcol(C.GREEN, 230)); p.setFont(QFont('Courier New', 8, QFont.Weight.Bold))
        p.drawText(QRectF(0, H-18, W, 15), Qt.AlignmentFlag.AlignCenter, self.status)

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0-100
        self._text  = "--"
        self.setFixedHeight(30)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        bar_h   = 3
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

class LogWidget(QTextBrowser):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextBrowser {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QTextBrowser a {{ color: #60c8ff; text-decoration: underline; }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(self._repair_display_text(text))

    def _repair_display_text(self, text: str) -> str:
        text = "" if text is None else str(text)
        markers = ("\u00c3\u0192", "\u00c3\u201a", "\u00c3\u00a2\u201a\u00ac", "\u00c3\u00a2\u201a\u00ac\u0152", "\u00c3\u00a2\u201a\u00ac\u00c2\u009d", "\u00c3\u00b0\u0152")
        if not any(m in text for m in markers):
            return text
        for enc in ("latin-1", "cp1252"):
            try:
                repaired = text.encode(enc).decode("utf-8")
            except Exception:
                continue
            if repaired and repaired.count("\ufffd") <= text.count("\ufffd"):
                return repaired
        return text

    def _enqueue(self, text: str):
        text = self._repair_display_text(text)
        if self._tag_for_text(text) == "you":
            self._flush_pending()
            self._append_entry(text, "you")
            return
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _tag_for_text(self, text: str) -> str:
        tl = text.lower()
        if tl.startswith(("you:", "leo:", "tú:", "tu:", "usuario:")):
            return "you"
        if tl.startswith("helena:"):
            return "ai"
        if tl.startswith("system:"):
            return "sys"
        if tl.startswith("file:"):
            return "file"
        if "err" in tl or tl.startswith("error:"):
            return "err"
        return "sys"

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        self._tag = self._tag_for_text(self._text)
        self._link_spans = find_http_url_spans(self._text)
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            end = min(len(self._text), self._pos + 16)
            self._insert_range(self._text, self._pos, end, self._tag, self._link_spans)
            self._pos = end
        else:
            self._tmr.stop()
            self._insert_newline()
            self._typing = False
            self._next()

    def _insert_range(self, text: str, start: int, end: int, tag: str, link_spans):
        colors = {
            "you": C.GREEN,
            "ai": "#ff73d7",
            "err": C.RED,
            "file": C.ACC,
            "sys": C.PRI,
        }
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        position = start
        while position < end:
            active_link = next(
                (span for span in link_spans if span[0] <= position < span[1]),
                None,
            )
            next_link_start = min(
                (span[0] for span in link_spans if span[0] > position),
                default=end,
            )
            segment_end = min(end, active_link[1] if active_link else next_link_start)
            if segment_end <= position:
                segment_end = position + 1
            char_format = QTextCharFormat()
            char_format.setForeground(
                qcol("#60c8ff" if active_link else colors.get(tag, C.TEXT))
            )
            if active_link:
                char_format.setAnchor(True)
                char_format.setAnchorHref(active_link[2])
                char_format.setFontUnderline(True)
            cursor.insertText(text[position:segment_end], char_format)
            position = segment_end
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _insert_newline(self):
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("\n")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _append_entry(self, text: str, tag: str):
        spans = find_http_url_spans(text)
        self._insert_range(text, 0, len(text), tag, spans)
        self._insert_newline()

    def _flush_pending(self):
        self._tmr.stop()
        if self._typing:
            if self._pos < len(self._text):
                self._insert_range(
                    self._text,
                    self._pos,
                    len(self._text),
                    self._tag,
                    self._link_spans,
                )
            self._insert_newline()
        self._typing = False
        queued, self._queue = self._queue, []
        for text in queued:
            self._append_entry(text, self._tag_for_text(text))

_FILE_ICONS = {
    "image":   ("IMG", "#00d4ff"), "video":   ("VID", "#ff6b00"),
    "audio":   ("AUD", "#cc44ff"), "pdf":     ("PDF", "#ff4444"),
    "word":    ("DOC", "#4488ff"), "excel":   ("XLS", "#44bb44"),
    "code":    ("CODE", "#ffcc00"), "archive": ("ZIP", "#ff8844"),
    "pptx":    ("PPT", "#ff6622"), "text":    ("TXT", "#aaaaaa"),
    "data":    ("DATA", "#88ddff"), "unknown": ("FILE", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class CyberCodeHighlighter(QSyntaxHighlighter):
    """Resaltador cyberpunk para Code Lab: Python, Java, JS, HTML, CSS, JSON, SQL, Bash."""
    def __init__(self, doc, lang_getter):
        super().__init__(doc)
        self._lang_getter = lang_getter
        self._fmt_keyword = self._fmt(C.PRI, bold=True)
        self._fmt_type    = self._fmt(C.ACC2, bold=True)
        self._fmt_string  = self._fmt("#baff8f")
        self._fmt_number  = self._fmt("#ffd76a")
        self._fmt_comment = self._fmt("#5a7890", italic=True)
        self._fmt_func    = self._fmt("#c084ff")
        self._fmt_symbol  = self._fmt(C.TEXT_MED)

    def _fmt(self, color, bold=False, italic=False):
        f = QTextCharFormat()
        f.setForeground(qcol(color))
        if bold: f.setFontWeight(QFont.Weight.Bold)
        if italic: f.setFontItalic(True)
        return f

    def _rx(self, pattern, fmt, text):
        it = QRegularExpression(pattern).globalMatch(text)
        while it.hasNext():
            m = it.next()
            self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

    def highlightBlock(self, text: str):
        lang = (self._lang_getter() or "").lower()
        common = r"\b(class|def|function|return|if|else|elif|for|while|switch|case|break|continue|try|catch|finally|import|from|package|public|private|protected|static|void|new|const|let|var|async|await|true|false|null|None|this|self|extends|implements|interface|enum|throw|throws|in|is|and|or|not)\b"
        types  = r"\b(int|float|double|str|string|String|bool|boolean|char|long|short|byte|dict|list|tuple|set|Map|List|Array|Object|Promise|Date|console|System|print|printf|println)\b"
        if lang == "sql":
            common = r"\b(SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|LEFT|RIGHT|INNER|OUTER|GROUP|ORDER|BY|HAVING|CREATE|TABLE|ALTER|DROP|INDEX|VALUES|INTO|AS|AND|OR|NOT|NULL|LIMIT|OFFSET)\b"
        elif lang in ("html", "xml"):
            self._rx(r"</>\w+[^>]*>", self._fmt_keyword, text)
            self._rx(r"\b(class|id|href|src|style|script|rel|type|name|value)=", self._fmt_type, text)
        elif lang == "css":
            self._rx(r"[.#]>[A-Za-z_][\w-]*(>=\s*\{)", self._fmt_keyword, text)
            self._rx(r"[A-Za-z-]+(>=\s*:)", self._fmt_type, text)
        self._rx(common, self._fmt_keyword, text)
        self._rx(types, self._fmt_type, text)
        self._rx(r"\b[A-Za-z_][\w_]*(>=\s*\()", self._fmt_func, text)
        self._rx(r"\b\d+(>:\.\d+)>\b", self._fmt_number, text)
        self._rx(r"'[^'\\]*(>:\\.[^'\\]*)*'|\"[^\"\\]*(>:\\.[^\"\\]*)*\"|`[^`]*`", self._fmt_string, text)
        self._rx(r"#.*$|//.*$|/\*.*\*/|<!--.*-->", self._fmt_comment, text)

class CodeLab(QWidget):
    send_code = pyqtSignal(str)

    EXT = {
        "PYTHON":"py", "JAVA":"java", "JAVASCRIPT":"js", "TYPESCRIPT":"ts",
        "HTML":"html", "CSS":"css", "JSON":"json", "SQL":"sql", "BASH":"sh",
        "C++":"cpp", "C#":"cs", "GO":"go", "RUST":"rs", "PHP":"php"
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: Path | None = None
        self._run_active = False
        self._run_thread: threading.Thread | None = None
        self._run_signals: _BackgroundTaskSignals | None = None
        self._run_button: QPushButton | None = None
        self._file_load_active = False
        self._file_load_generation = 0
        self._file_load_thread: threading.Thread | None = None
        self._file_load_signals: _BackgroundTaskSignals | None = None
        self.setMinimumHeight(285)
        self.setStyleSheet(f"""
            CodeLab {{
                background: rgba(3, 10, 24, 230);
                border: 1px solid {C.BORDER_A};
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(7)

        top = QHBoxLayout(); top.setSpacing(8)
        title = QLabel("CODE LAB")
        title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent; letter-spacing: 2px;")
        top.addWidget(title)
        top.addStretch()
        self._lang = QComboBox()
        self._lang.addItems(list(self.EXT.keys()))
        self._lang.setCurrentText("PYTHON")
        self._lang.setFixedHeight(26)
        self._lang.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._lang.setStyleSheet(f"""
            QComboBox {{
                background: #020b19; color: {C.PRI};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 2px 8px;
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{ background: #020b19; color: {C.WHITE}; selection-background-color: {C.PRI_GHO}; }}
        """)
        top.addWidget(self._lang)
        lay.addLayout(top)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Pegá código acá o recibí bloques de código de Helena...")
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setAcceptRichText(False)
        self.editor.setStyleSheet(f"""
            QTextEdit {{
                background: #020814;
                color: {C.WHITE};
                border: 1px solid {C.BORDER};
                border-radius: 5px;
                padding: 9px;
                selection-background-color: {C.PRI_GHO};
                line-height: 125%;
            }}
            QScrollBar:vertical {{ background: #020814; width: 14px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 6px; min-height: 34px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        lay.addWidget(self.editor, stretch=1)
        self._hl = CyberCodeHighlighter(self.editor.document(), lambda: self._lang.currentText())
        self._lang.currentTextChanged.connect(lambda _: self._hl.rehighlight())

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFixedHeight(44)
        self.console.setFont(QFont("Consolas", 8))
        self.console.setText("> consola preparada\n> salida de ejecución / mensajes")
        self.console.setStyleSheet(f"background:#01050d; color:{C.TEXT_MED}; border:1px solid {C.BORDER}; border-radius:5px; padding:5px;")
        lay.addWidget(self.console)

        row = QHBoxLayout(); row.setSpacing(6)
        for txt, cb, accent in [
            ("OPEN", self.open_code, False),
            ("RUN", self.run_code, True),
            ("SAVE", self.save_code, False),
            ("SAVE AS", self.save_code_as, False),
            ("COPY", self.copy_code, False),
            ("SEND", self._send_current, False),
            ("CLEAR", self.editor.clear, False),
        ]:
            b = QPushButton(txt)
            b.setFixedHeight(28)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            bg = C.PRI_GHO if accent else "#020b19"
            col = C.ACC2 if accent else C.TEXT
            br = C.ACC if accent else C.BORDER
            b.setStyleSheet(f"""
                QPushButton {{ background: {bg}; color: {col}; border: 1px solid {br}; border-radius: 5px; }}
                QPushButton:hover {{ color: {C.PRI}; border: 1px solid {C.PRI}; }}
            """)
            b.clicked.connect(cb)
            if txt == "RUN":
                self._run_button = b
            row.addWidget(b)
        lay.addLayout(row)

    def set_code(self, code: str):
        code = (code or "").strip("\n")
        if code:
            self.editor.setPlainText(code)
            self._hl.rehighlight()
            self.console.setPlainText("> bloque recibido desde HELENA")

    def set_file(self, path: str, code: str | None = None):
        p = Path(path).expanduser()
        if code is None:
            self._load_file_async(p)
            return
        self._file_load_generation += 1
        self._file_load_active = False
        self._file_load_thread = None
        self._file_load_signals = None
        self.setEnabled(True)
        self._apply_file(p, code)

    def _apply_file(self, path: Path, code: str):
        self._current_path = path
        self.editor.setPlainText(code)
        self._set_language_from_path(path)
        self._hl.rehighlight()
        self.console.setPlainText(f"> archivo activo: {path}")

    def _load_file_async(self, path: Path):
        if self._file_load_active:
            self.console.setPlainText("> ya hay una lectura de archivo en curso")
            return
        self._file_load_active = True
        self._file_load_generation += 1
        generation = self._file_load_generation
        self._current_path = path
        self._set_language_from_path(path)
        self.console.setPlainText("> leyendo archivo en segundo plano...")
        self.setEnabled(False)

        signals = _BackgroundTaskSignals()
        signals.result.connect(self._on_file_loaded)
        self._file_load_signals = signals

        def read_file():
            try:
                result = (generation, path, read_code_file(path), None)
            except Exception as exc:
                result = (generation, path, None, str(exc))
            signals.result.emit(result)

        self._file_load_thread = threading.Thread(
            target=read_file,
            name="helena-code-lab-file-reader",
            daemon=True,
        )
        try:
            self._file_load_thread.start()
        except RuntimeError as exc:
            self._on_file_loaded((generation, path, None, str(exc)))

    def _on_file_loaded(self, result):
        generation, path, code, error = result
        if generation != self._file_load_generation:
            return
        self._file_load_active = False
        self._file_load_thread = None
        self._file_load_signals = None
        self.setEnabled(True)
        if error is not None:
            self.console.setPlainText(f"ERROR > no se pudo leer el archivo: {error}")
            return
        self._apply_file(path, code)

    def _set_language_from_path(self, path: Path):
        ext = path.suffix.lower().lstrip(".")
        for lang, lang_ext in self.EXT.items():
            if ext == lang_ext:
                self._lang.setCurrentText(lang)
                return

    def get_code(self) -> str:
        return self.editor.toPlainText()

    def copy_code(self):
        QApplication.clipboard().setText(self.get_code())
        self.console.setPlainText("> código copiado al portapapeles")

    def open_code(self):
        filt = "Código (*.py *.java *.js *.ts *.html *.css *.json *.sql *.sh *.cpp *.cs *.go *.rs *.php);;Todos (*.*)"
        path, _ = QFileDialog.getOpenFileName(self, "Abrir código", str(BASE_DIR), filt)
        if path:
            try:
                self.set_file(path)
            except Exception as e:
                self.console.setPlainText(f"ERROR > {e}")

    def save_code(self):
        if self._current_path:
            try:
                self._current_path.write_text(self.get_code(), encoding="utf-8")
                self.console.setPlainText(f"> guardado: {self._current_path}")
                return
            except Exception as e:
                self.console.setPlainText(f"ERROR > {e}")
                return
        self.save_code_as()

    def save_code_as(self):
        ext = self.EXT.get(self._lang.currentText(), "txt")
        filt = "Código (*.py *.java *.js *.ts *.html *.css *.json *.sql *.sh *.cpp *.cs *.go *.rs *.php);;Todos (*.*)"
        path, _ = QFileDialog.getSaveFileName(self, "Guardar código", f"helena_code.{ext}", filt)
        if path:
            p = Path(path)
            p.write_text(self.get_code(), encoding="utf-8")
            self._current_path = p
            self._set_language_from_path(p)
            self.console.setPlainText(f"> guardado: {p}")

    def run_code(self):
        lang = self._lang.currentText().upper()
        code = self.get_code()
        if not code.strip():
            self.console.setPlainText("> no hay código para ejecutar")
            return
        if self._run_active:
            return

        self._run_active = True
        self.console.setPlainText("> ejecutando en segundo plano...")
        if self._run_button is not None:
            self._run_button.setEnabled(False)

        signals = _BackgroundTaskSignals()
        signals.result.connect(self._on_run_finished)
        self._run_signals = signals

        def execute():
            signals.result.emit(execute_code(lang, code, _helena_run_hidden))

        self._run_thread = threading.Thread(
            target=execute,
            name="helena-code-lab-runner",
            daemon=True,
        )
        try:
            self._run_thread.start()
        except RuntimeError as exc:
            self._on_run_finished(f"ERROR > no se pudo iniciar la ejecución: {exc}")

    def _on_run_finished(self, output: str):
        self._run_active = False
        self._run_thread = None
        self._run_signals = None
        if self._run_button is not None:
            self._run_button.setEnabled(True)
        self.console.setPlainText(str(output))

    def _send_current(self):
        code = self.get_code().strip()
        if code:
            lang = self._lang.currentText().lower()
            self.console.setPlainText(f"> enviado a HELENA como {lang}")
            self.send_code.emit(f"```{lang}\n{code}\n```")


class ProjectExplorerWidget(QWidget):
    """Project utility used by the CODE LAB page.

    It can load a folder or ZIP and creates a compact project map that HELENA can
    receive as context.  The real editor stays in the CODE LAB tab.
    """
    send_project = pyqtSignal(str)
    project_selected = pyqtSignal(str)

    SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env', 'dist', 'build', '.idea', '.vscode'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_path: str | None = None
        self._summary = ''
        self._scan_active = False
        self._scan_thread: threading.Thread | None = None
        self._scan_signals: _BackgroundTaskSignals | None = None
        self.setMinimumHeight(250)
        self.setStyleSheet(f"""
            ProjectExplorerWidget {{
                background: rgba(3, 10, 24, 230);
                border: 1px solid {C.BORDER_A};
                border-radius: 8px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 9, 10, 9)
        lay.setSpacing(7)

        top = QHBoxLayout(); top.setSpacing(8)
        title = QLabel('PROJECT FILES')
        title.setFont(QFont('Courier New', 11, QFont.Weight.Bold))
        title.setStyleSheet(f'color:{C.TEXT}; background:transparent; letter-spacing:2px;')
        top.addWidget(title); top.addStretch()
        badge = QLabel('PROJECT MAP')
        badge.setFont(QFont('Courier New', 8, QFont.Weight.Bold))
        badge.setStyleSheet(f'color:{C.PRI}; border:1px solid {C.BORDER}; border-radius:4px; padding:4px 8px; background:#020b19;')
        top.addWidget(badge)
        lay.addLayout(top)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont('Consolas', 9))
        self.view.setText('> Cargá una carpeta o ZIP para que HELENA vea la estructura del proyecto.\n> Ideal para revisar archivos, scripts, recursos y builds.\n\nSin proyecto activo.')
        self.view.setStyleSheet(f"""
            QTextEdit {{
                background:#020814; color:{C.TEXT_MED}; border:1px solid {C.BORDER};
                border-radius:5px; padding:8px; selection-background-color:{C.PRI_GHO};
            }}
            QScrollBar:vertical {{ background:#020814; width:14px; margin:2px; }}
            QScrollBar::handle:vertical {{ background:{C.BORDER_B}; border-radius:6px; min-height:34px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0px; }}
        """)
        lay.addWidget(self.view, stretch=1)

        row = QHBoxLayout(); row.setSpacing(6)
        buttons = [
            ('FOLDER', self.open_folder, True),
            ('ZIP', self.open_zip, False),
            ('SEND', self.send_to_helena, False),
            ('CLEAR', self.clear, False),
        ]
        for txt, cb, accent in buttons:
            b = QPushButton(txt)
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont('Courier New', 8, QFont.Weight.Bold))
            bg = C.PRI_GHO if accent else '#020b19'
            col = C.ACC2 if accent else C.TEXT
            br = C.ACC if accent else C.BORDER
            b.setStyleSheet(f"""
                QPushButton {{ background:{bg}; color:{col}; border:1px solid {br}; border-radius:5px; }}
                QPushButton:hover {{ color:{C.PRI}; border:1px solid {C.PRI}; }}
            """)
            b.clicked.connect(cb)
            row.addWidget(b)
        lay.addLayout(row)

    def open_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Seleccioná carpeta de proyecto', str(Path.home()))
        if path:
            self.load_path(path)

    def open_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Seleccioná ZIP de proyecto', str(Path.home()), 'ZIP (*.zip);;Todos (*.*)')
        if path:
            self.load_path(path)

    def load_path(self, path: str):
        if self._scan_active:
            return
        self._project_path = path
        self._scan_active = True
        self.view.setPlainText("> analizando estructura del proyecto...")
        self.setEnabled(False)

        signals = _BackgroundTaskSignals()
        signals.result.connect(self._on_path_loaded)
        self._scan_signals = signals

        def scan():
            try:
                summary = build_project_summary(
                    path,
                    self.SKIP_DIRS,
                    _file_category,
                    _fmt_size,
                )
                result = (path, summary, None)
            except Exception as exc:
                result = (path, None, str(exc))
            signals.result.emit(result)

        self._scan_thread = threading.Thread(
            target=scan,
            name="helena-project-scanner",
            daemon=True,
        )
        try:
            self._scan_thread.start()
        except RuntimeError as exc:
            self._on_path_loaded((path, None, str(exc)))

    def _on_path_loaded(self, result):
        path, summary, error = result
        self._scan_active = False
        self._scan_thread = None
        self._scan_signals = None
        self.setEnabled(True)
        if error is not None:
            self.view.setPlainText(f'ERROR > no pude leer el proyecto: {error}')
            return
        self._summary = summary
        self.view.setPlainText(self._summary)
        self.project_selected.emit(path)

    def _scan_folder(self, folder: Path) -> str:
        return build_project_summary(folder, self.SKIP_DIRS, _file_category, _fmt_size)

    def _scan_zip(self, path: Path) -> str:
        return build_project_summary(path, self.SKIP_DIRS, _file_category, _fmt_size)

    def send_to_helena(self):
        if not self._summary:
            self.view.setPlainText('> no hay proyecto cargado todavía')
            return
        self.send_project.emit('[PROJECT_CONTEXT]\n' + self._summary)

    def clear(self):
        self._project_path = None
        self._summary = ''
        self.view.setPlainText('> Proyecto limpiado.\n> Cargá una carpeta o ZIP cuando quieras.')


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(76)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccioná un archivo para HELENA", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Soltá un archivo o hacé clic")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Imágenes - Video - Audio - PDF - Docs - Código")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "DROP")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Soltá para cargar")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  -  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "..." + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "X")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl(">  CONFIGURACIÓN NECESARIA", 13, True))
        layout.addWidget(_lbl("Configurá HELENA antes del primer inicio.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("CLAVE API GEMINI", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza...")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addSpacing(8)

        layout.addWidget(_lbl("CLAVE API OPENROUTER", 8, color=C.TEXT_DIM,
                       align=Qt.AlignmentFlag.AlignLeft))
        self._or_input = QLineEdit()
        self._or_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._or_input.setPlaceholderText("sk-or-...")
        self._or_input.setFont(QFont("Courier New", 10))
        self._or_input.setFixedHeight(32)
        self._or_input.setStyleSheet(f"""
            QLineEdit {{
                background: #000d12; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.ACC2}; }}
        """)
        layout.addWidget(self._or_input)

        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("SISTEMA OPERATIVO", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Detectado: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","Windows"),("mac","macOS"),("linux","Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton(">  INICIAR SISTEMA")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        or_key = self._or_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        if not or_key:
            self._or_input.setStyleSheet(
                self._or_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, or_key, self._sel_os)


class MainWindow(QMainWindow):
    _log_sig   = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _code_sig  = pyqtSignal(str)
    _syslog_sig = pyqtSignal(str)

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("HELENA - CORE V6.4 FINAL")
        self._quit_requested = False
        self._tray_icon = None
        self._tray_menu = None
        self._tray_ready = False
        self._app_icon = _helena_icon()
        if not self._app_icon.isNull():
            self.setWindowIcon(self._app_icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(self._app_icon)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(max(0, (screen.width() - _DEFAULT_W)//2), max(0, (screen.height() - _DEFAULT_H)//2))

        self.on_text_command = None
        self._muted = False
        self._current_file: str | None = None
        self._overlay: SetupOverlay | None = None
        self._active_page = "CORE"
        self._tab_buttons: dict[str, QPushButton] = {}

        central = QWidget()
        central.setObjectName("CentralRoot")
        central.setStyleSheet(f"""
            QWidget#CentralRoot {{ background: {C.BG}; }}
            QLabel {{ background: transparent; }}
        """)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(6, 6, 6, 0)
        body.setSpacing(8)
        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self._page_stack = QStackedWidget()
        self._page_stack.setStyleSheet("background: transparent;")
        self._page_stack.addWidget(self._build_core_page(face_path))
        self._page_stack.addWidget(self._build_lab_page())
        self._page_stack.addWidget(self._build_system_page())
        body.addWidget(self._page_stack, stretch=1)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)
        root.addLayout(body, stretch=1)

        root.addWidget(self._build_command_bar())
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._append_log)
        self._syslog_sig.connect(self._append_system_log)
        self._state_sig.connect(self._apply_state)
        self._code_sig.connect(self._set_code_all)

        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)

        self._init_tray_icon()
        self._switch_page("CORE")


    # ---------- system tray / taskbar ----------
    def _init_tray_icon(self):
        """Instala el icono de HELENA en la bandeja del sistema.

        La X de la ventana no mata a Helena: solo oculta el HUD y deja vivos
        el micrófono, Discord, WebSocket y la sesión principal.
        """
        if self._tray_ready:
            return
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                self._append_system_log("SYSTEM: bandeja del sistema no disponible; la X cerrará normalmente si Qt lo requiere.")
                return

            icon = self._app_icon if not self._app_icon.isNull() else self.windowIcon()
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip("HELENA CORE V6.4 - ejecutándose")

            menu = QMenu(self)

            act_show = QAction("Mostrar Helena", self)
            act_show.triggered.connect(self._tray_show)
            menu.addAction(act_show)

            act_hide = QAction("Ocultar a bandeja", self)
            act_hide.triggered.connect(self._tray_hide)
            menu.addAction(act_hide)

            menu.addSeparator()

            act_discord_in = QAction("Entrar a Discord", self)
            act_discord_in.triggered.connect(lambda: self._send_tray_command("Helena metete a Discord"))
            menu.addAction(act_discord_in)

            act_discord_out = QAction("Salir de Discord", self)
            act_discord_out.triggered.connect(lambda: self._send_tray_command("Helena salí de Discord"))
            menu.addAction(act_discord_out)

            act_discord_restart = QAction("Reiniciar Discord", self)
            act_discord_restart.triggered.connect(lambda: self._send_tray_command("Helena reiniciá Discord"))
            menu.addAction(act_discord_restart)

            menu.addSeparator()

            act_mute_local = QAction("Mute / Desmute micrófono local", self)
            act_mute_local.triggered.connect(self._toggle_mute)
            menu.addAction(act_mute_local)

            act_mute_discord = QAction("Mute Discord", self)
            act_mute_discord.triggered.connect(lambda: self._send_tray_command("Helena muteate"))
            menu.addAction(act_mute_discord)

            act_unmute_discord = QAction("Desmute Discord", self)
            act_unmute_discord.triggered.connect(lambda: self._send_tray_command("Helena desmuteate"))
            menu.addAction(act_unmute_discord)

            menu.addSeparator()

            act_quit = QAction("Cerrar Helena definitivamente", self)
            act_quit.triggered.connect(self._tray_quit)
            menu.addAction(act_quit)

            tray.setContextMenu(menu)
            tray.activated.connect(self._on_tray_activated)
            tray.show()

            self._tray_icon = tray
            self._tray_menu = menu
            self._tray_ready = True
            self._append_system_log("SYSTEM: icono de bandeja activo. La X oculta HELENA sin cerrar el proceso.")
        except Exception as e:
            self._append_system_log(f"SYSTEM: no pude iniciar icono de bandeja: {e}")

    def _send_tray_command(self, text: str):
        self._append_log(f"USUARIO: {text}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()
        else:
            self._append_system_log("SYSTEM: comando de bandeja sin handler activo todavía")

    def _tray_show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._append_system_log("SYSTEM: HELENA mostrada desde bandeja")

    def _tray_hide(self):
        self.hide()
        self._append_system_log("SYSTEM: HELENA ocultada en bandeja")

    def _tray_quit(self):
        self._quit_requested = True
        if self._tray_icon:
            self._tray_icon.hide()
        self._append_system_log("SYSTEM: cierre definitivo solicitado desde bandeja")
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            self.close()

    def _on_tray_activated(self, reason):
        # Doble click: mostrar/restaurar. Click simple se deja al sistema.
        try:
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self._tray_show()
        except Exception:
            pass

    def closeEvent(self, event):
        if getattr(self, "_quit_requested", False):
            event.accept()
            return
        if getattr(self, "_tray_ready", False) and self._tray_icon:
            event.ignore()
            self.hide()
            self._append_system_log("SYSTEM: X presionada. HELENA sigue ejecutándose en la bandeja del sistema.")
            try:
                self._tray_icon.showMessage(
                    "HELENA sigue activa",
                    "Cerré el HUD, pero sigo ejecutándome. Clic derecho en el icono para salir definitivamente.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500,
                )
            except Exception:
                pass
            return
        event.accept()

    # ---------- builders ----------
    def _panel(self, title: str | None = None) -> QWidget:
        box = QWidget()
        box.setStyleSheet(f"""
            QWidget {{ background: rgba(1, 10, 24, 218); border: 1px solid rgba(0, 229, 255, 92); border-radius: 8px; }}
            QLabel {{ border: none; background: transparent; }}
        """)
        lay = QVBoxLayout(box); lay.setContentsMargins(12, 10, 12, 10); lay.setSpacing(8)
        if title:
            lbl = QLabel(title)
            lbl.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color:{C.WHITE}; letter-spacing:1px;")
            lay.addWidget(lbl)
        box._inner_layout = lay  # type: ignore[attr-defined]
        return box

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(58)
        w.setStyleSheet(f"background: rgba(0, 5, 14, 245); border-bottom: 1px solid rgba(0, 229, 255, 96);")
        lay = QHBoxLayout(w); lay.setContentsMargins(16, 0, 16, 0); lay.setSpacing(16)

        brand = QVBoxLayout(); brand.setSpacing(0)
        title = QLabel("H E L E N A")
        title.setFont(QFont("Courier New", 21, QFont.Weight.Bold))
        title.setStyleSheet(f"color:{C.PRI}; letter-spacing:8px;")
        sub = QLabel("HOLOGRAPHIC EMOTIONAL AI ASSISTANT   -   v6.4 FINAL HUD")
        sub.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        sub.setStyleSheet(f"color:{C.TEXT_MED};")
        brand.addWidget(title); brand.addWidget(sub)
        lay.addLayout(brand, stretch=0)
        lay.addStretch(1)

        tabs = QHBoxLayout(); tabs.setSpacing(44)
        for name in ("CORE", "CODE LAB", "SYSTEM"):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(150, 40)
            b.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
            b.clicked.connect(lambda _=False, n=name: self._switch_page(n))
            self._tab_buttons[name] = b
            tabs.addWidget(b)
        lay.addLayout(tabs, stretch=2)
        lay.addStretch(1)

        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._clock_lbl.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color:{C.PRI};")
        lay.addWidget(self._clock_lbl, stretch=0)

        return w

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)

        status = self._panel("SYSTEM STATUS")
        status_lay = status._inner_layout  # type: ignore[attr-defined]
        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("RAM", C.ACC2)
        self._bar_net = MetricBar("NET", C.PRI)
        for b in (self._bar_cpu, self._bar_mem, self._bar_net):
            status_lay.addWidget(b)
        lay.addWidget(status, stretch=0)

        voice = self._panel("VOICE INPUT")
        vlay = voice._inner_layout  # type: ignore[attr-defined]
        self._voice_wave = VoiceWaveWidget()
        vlay.addWidget(self._voice_wave)
        lay.addWidget(voice, stretch=0)

        core = self._panel("CORE STATUS")
        clay = core._inner_layout  # type: ignore[attr-defined]
        self._core_status_widget = CoreStatusWidget()
        clay.addWidget(self._core_status_widget)
        lay.addWidget(core, stretch=0)

        qf = self._panel("QUICK FILES")
        qlay = qf._inner_layout  # type: ignore[attr-defined]
        grid = QGridLayout(); grid.setSpacing(7)
        for i, (txt, tip) in enumerate([("N", "NOTES"), ("S", "SCRIPTS"), ("M", "MEDIA"), ("L", "LOGS"), ("P", "PROFILE"), ("C", "CONFIG")]):
            btn = QPushButton(f"{txt}\n{tip}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(40)
            btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            btn.setStyleSheet(f"""
                QPushButton {{ background:#020b19; color:{C.TEXT}; border:1px solid {C.BORDER}; border-radius:6px; }}
                QPushButton:hover {{ color:{C.PRI}; border:1px solid {C.PRI}; background:#03182a; }}
            """)
            btn.clicked.connect(lambda _=False, action=tip: self._quick_file_action(action))
            grid.addWidget(btn, i//3, i%3)
        qlay.addLayout(grid)
        lay.addWidget(qf, stretch=0)

        mode = self._panel("AI MODE")
        mlay = mode._inner_layout  # type: ignore[attr-defined]
        self._mode_lbl = QLabel("EMOTIONAL")
        self._mode_lbl.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        self._mode_lbl.setStyleSheet("color:#ff73d7;")
        mlay.addWidget(self._mode_lbl)
        lay.addWidget(mode, stretch=0)
        lay.addStretch(1)
        return w

    def _build_core_page(self, face_path: str) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background: rgba(2, 8, 20, 230); border: 1px solid rgba(0, 229, 255, 80); border-radius: 10px;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.hud = HudCanvas(face_path)
        lay.addWidget(self.hud, stretch=1)
        return w

    def _build_lab_page(self) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background: rgba(2, 8, 20, 230); border:1px solid rgba(0,229,255,80); border-radius:10px;")
        lay = QVBoxLayout(w); lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(10)
        title = QLabel("CODE LAB // DEVELOPER MODE")
        title.setFont(QFont("Courier New", 13, QFont.Weight.Bold)); title.setStyleSheet(f"color:{C.PRI};")
        lay.addWidget(title)
        self._lab_big = CodeLab()
        self._lab_big.send_code.connect(self._send_code_from_lab)
        lay.addWidget(self._lab_big, stretch=1)
        self._lab_console = QTextEdit(); self._lab_console.setReadOnly(True); self._lab_console.setFixedHeight(88)
        self._lab_console.setFont(QFont("Consolas", 9)); self._lab_console.setText("> HELENA LAB READY\n> Python/Java runner ready - Project explorer on right panel\n> Multi-language syntax highlighter online")
        self._lab_console.setStyleSheet(f"background:#01050d; color:{C.TEXT_MED}; border:1px solid {C.BORDER_A}; border-radius:7px; padding:8px;")
        lay.addWidget(self._lab_console)
        return w

    def _build_system_page(self) -> QWidget:
        w = QWidget(); w.setStyleSheet(f"background: rgba(2, 8, 20, 230); border:1px solid rgba(0,229,255,80); border-radius:10px;")
        lay = QVBoxLayout(w); lay.setContentsMargins(16, 16, 16, 16); lay.setSpacing(12)
        title = QLabel("SYSTEM // LOG / VISOR DE SUCESOS")
        title.setFont(QFont("Courier New", 14, QFont.Weight.Bold)); title.setStyleSheet(f"color:{C.PRI};")
        lay.addWidget(title)

        tools = QHBoxLayout(); tools.setSpacing(8)
        for label, cb in [
            ("CLEAR LOG", self._clear_system_log),
            ("COPY LOG", self._copy_system_log),
            ("SAVE LOG", self._save_system_log),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setStyleSheet(f"QPushButton{{background:#020b19;color:{C.TEXT};border:1px solid {C.BORDER};border-radius:5px;}} QPushButton:hover{{color:{C.PRI};border:1px solid {C.PRI};}}")
            b.clicked.connect(cb)
            tools.addWidget(b)
        tools.addStretch(1)
        lay.addLayout(tools)
        grid = QGridLayout(); grid.setSpacing(10)
        self._sys_cards = {}
        for i, name in enumerate(["CPU", "RAM", "NET", "VOICE", "AI CORE", "RIG"]):
            box = self._panel(name)
            il = box._inner_layout  # type: ignore[attr-defined]
            val = QLabel("--")
            val.setFont(QFont("Courier New", 20, QFont.Weight.Bold)); val.setStyleSheet(f"color:{C.PRI};")
            il.addWidget(val)
            self._sys_cards[name] = val
            grid.addWidget(box, i//3, i%3)
        lay.addLayout(grid)
        self._system_console = QTextEdit(); self._system_console.setReadOnly(True)
        self._system_console.setFont(QFont("Consolas", 9))
        self._system_console.setText("[SYS] Facial rig v6.4 loaded from assets/helena_rig\n[SYS] Blink/Speak/Eye tracking timers active\n[SYS] UI pages online: CORE, CODE LAB, SYSTEM")
        self._system_console.setStyleSheet(f"background:#01050d; color:{C.TEXT_MED}; border:1px solid {C.BORDER_A}; border-radius:7px; padding:10px;")
        lay.addWidget(self._system_console, stretch=1)
        return w

    def _build_right_panel(self) -> QWidget:
        w = QWidget(); w.setFixedWidth(_RIGHT_W); w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        logbox = self._panel("CONVERSACIÓN")
        self._right_conversation_box = logbox
        self._right_logbox = logbox  # compatibilidad con parches anteriores
        log_lay = logbox._inner_layout  # type: ignore[attr-defined]
        self._log = LogWidget()
        if hasattr(self, '_system_console'):
            self._append_system_log("SYSTEM: Helena v6.4 final online")
            self._append_system_log("SYSTEM: Facial rig connected")
            self._append_system_log("SYSTEM: Core systems optimal")
        log_lay.addWidget(self._log, stretch=1)
        lay.addWidget(logbox, stretch=2)

        projectbox = self._panel(None)
        self._right_projectbox = projectbox
        p_lay = projectbox._inner_layout  # type: ignore[attr-defined]
        self._project_explorer = ProjectExplorerWidget()
        self._project_explorer.project_selected.connect(self._on_project_selected)
        self._project_explorer.send_project.connect(self._send_project_summary)
        p_lay.addWidget(self._project_explorer, stretch=1)
        lay.addWidget(projectbox, stretch=3)
        return w

    def _build_command_bar(self) -> QWidget:
        w = QWidget(); w.setFixedHeight(58)
        w.setStyleSheet(f"background: rgba(0, 5, 14, 245); border-top:1px solid rgba(0,229,255,70); border-bottom:1px solid rgba(0,229,255,70);")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 7, 14, 7); lay.setSpacing(10)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Escribí un comando o pregunta...")
        self._input.setFont(QFont("Courier New", 11))
        self._input.setFixedHeight(40)
        self._input.setStyleSheet(f"""
            QLineEdit {{ background:#020814; color:{C.WHITE}; border:1px solid {C.BORDER}; border-radius:7px; padding: 4px 14px; }}
            QLineEdit:focus {{ border:1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        lay.addWidget(self._input, stretch=1)
        send = QPushButton(">")
        send.setFixedSize(48, 40); send.setCursor(Qt.CursorShape.PointingHandCursor); send.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
        send.setStyleSheet(f"QPushButton{{background:#020b19;color:{C.PRI};border:1px solid {C.BORDER_A};border-radius:7px;}} QPushButton:hover{{border:1px solid {C.PRI};}}")
        send.clicked.connect(self._send)
        lay.addWidget(send)
        self._mute_btn = QPushButton("MIC")
        self._mute_btn.setFixedSize(48, 40); self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor); self._mute_btn.clicked.connect(self._toggle_mute)
        lay.addWidget(self._mute_btn)
        self._file_hint = QLabel("PROJECT: sin cargar - FOLDER/ZIP desde panel derecho")
        self._file_hint.setMinimumWidth(330)
        self._file_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_hint.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._file_hint.setStyleSheet(f"color:{C.TEXT_MED}; background:#020814; border:1px solid {C.BORDER}; border-radius:7px; padding:8px;")
        lay.addWidget(self._file_hint, stretch=0)
        self._style_mute_btn()
        return w

    def _build_footer(self) -> QWidget:
        w = QWidget(); w.setFixedHeight(56)
        w.setStyleSheet(f"background: rgba(0, 5, 14, 250); border-top: 1px solid rgba(0,229,255,90);")
        lay = QHBoxLayout(w); lay.setContentsMargins(20, 6, 20, 6); lay.setSpacing(26)
        self._footer_labels = {}
        for title, value, flex in [("TIME","--:--:--",1),("UPTIME","--:--",1),("MODE","CORE",1),("NETWORK","--",2),("VOICE","ACTIVE",1),("AI CORE","100%",2),("BUILD","v6.3",1)]:
            box = QWidget(); box.setStyleSheet("background: transparent; border-left: 1px solid rgba(0,229,255,42);")
            bl = QVBoxLayout(box); bl.setContentsMargins(12,2,8,2); bl.setSpacing(0)
            t=QLabel(title); t.setFont(QFont("Courier New",7,QFont.Weight.Bold)); t.setStyleSheet(f"color:{C.TEXT_MED};")
            v=QLabel(value); v.setFont(QFont("Courier New",12,QFont.Weight.Bold)); v.setStyleSheet(f"color:{C.PRI};")
            bl.addWidget(t); bl.addWidget(v); self._footer_labels[title]=v
            lay.addWidget(box, stretch=flex)
        return w

    # ---------- behaviour ----------
    def _style_tab_buttons(self):
        for name, b in self._tab_buttons.items():
            active = (name == self._active_page)
            b.setChecked(active)
            b.setStyleSheet(f"""
                QPushButton {{ background:{'#03182a' if active else 'transparent'}; color:{C.PRI if active else C.TEXT_MED};
                    border:none; border-bottom:{'2px solid '+C.PRI if active else '1px solid transparent'}; }}
                QPushButton:hover {{ color:{C.PRI}; border-bottom:1px solid {C.PRI_DIM}; }}
            """)

    def _switch_page(self, name: str):
        self._active_page = name
        if hasattr(self, '_page_stack'):
            idx = {"CORE": 0, "CODE LAB": 1, "SYSTEM": 2}.get(name, 0)
            self._page_stack.setCurrentIndex(idx)
        self._style_tab_buttons()

        # V20: CORE = conversación; SYSTEM = log técnico; CODE LAB = editor/proyecto.
        if hasattr(self, '_right_panel'):
            self._right_panel.setVisible(name in ("CORE", "CODE LAB"))
        if hasattr(self, '_right_conversation_box'):
            self._right_conversation_box.setVisible(name == "CORE")
        elif hasattr(self, '_right_logbox'):
            self._right_logbox.setVisible(name == "CORE")
        if hasattr(self, '_right_projectbox'):
            self._right_projectbox.setVisible(name == "CODE LAB")

        if hasattr(self, '_footer_labels'):
            self._footer_labels.get("MODE", QLabel()).setText(name.replace("CODE LAB", "LAB"))
        if hasattr(self, '_system_console'):
            self._append_system_log(f"SYSTEM: modo {name} activo")

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 430; cw = self.centralWidget()
            self._overlay.setGeometry((cw.width()-ow)//2, (cw.height()-oh)//2, ow, oh)

    def _tick_clock(self):
        now = time.strftime("%H:%M:%S")
        if hasattr(self, '_clock_lbl'): self._clock_lbl.setText(now)
        if hasattr(self, '_footer_labels'): self._footer_labels.get("TIME", QLabel()).setText(now)

    def _update_metrics(self):
        snap = _metrics.snapshot()
        cpu, mem, net = snap['cpu'], snap['mem'], snap['net']
        if hasattr(self, '_bar_cpu'):
            self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")
            self._bar_mem.set_value(mem, f"{mem:.0f}%")
            net_str = f"{net*1024:.0f}KB/s" if net < 1.0 else f"{net:.1f}MB/s"
            self._bar_net.set_value(min(100, net*10), net_str)
        if hasattr(self, '_sys_cards'):
            self._sys_cards['CPU'].setText(f"{cpu:.0f}%")
            self._sys_cards['RAM'].setText(f"{mem:.0f}%")
            self._sys_cards['NET'].setText(f"{net*1024:.0f} KB/s" if net < 1 else f"{net:.1f} MB/s")
            self._sys_cards['VOICE'].setText("MUTED" if self._muted else "ACTIVE")
            self._sys_cards['AI CORE'].setText("100%")
            self._sys_cards['RIG'].setText("ONLINE")
        if hasattr(self, '_footer_labels'):
            self._footer_labels['NETWORK'].setText(f"{net*1024:.0f} KB/s" if net < 1 else f"{net:.1f} MB/s")
            try:
                elapsed = time.time() - psutil.boot_time(); h = int(elapsed//3600); m = int((elapsed%3600)//60)
                uptime_txt = f"{h:02d}:{m:02d}"
                self._footer_labels['UPTIME'].setText(uptime_txt)
            except Exception:
                uptime_txt = "--:--"
            if hasattr(self, '_core_status_widget'):
                self._core_status_widget.update_values(cpu, mem, snap.get('tmp', -1.0), uptime_txt)

    def _is_conversation_line(self, text: str) -> bool:
        return is_conversation_line(text)

    def _append_system_log(self, text: str):
        if not hasattr(self, '_system_console') or text is None:
            return
        raw = str(text).rstrip("\n")
        if not raw:
            return
        for line in raw.splitlines():
            if line.strip():
                self._system_console.append(line)
        try:
            doc = self._system_console.document()
            max_blocks = 2500
            if doc.blockCount() > max_blocks:
                cursor = self._system_console.textCursor()
                cursor.movePosition(cursor.MoveOperation.Start)
                for _ in range(doc.blockCount() - max_blocks):
                    cursor.select(cursor.SelectionType.BlockUnderCursor)
                    cursor.removeSelectedText()
                    cursor.deleteChar()
        except Exception:
            pass

    def _append_log(self, text: str):
        # V20: CORE recibe solo conversación; SYSTEM recibe log técnico y sucesos.
        if self._is_conversation_line(text):
            if hasattr(self, '_log'):
                self._log.append_log(text)
        else:
            self._append_system_log(text)

        if hasattr(self, '_lab_console') and isinstance(text, str) and ('```' in text or 'código' in text.lower() or 'code' in text.lower()):
            self._lab_console.append(text[:500])
        # Visual speech fallback: even when the audio API does not send a speaking
        # state, HELENA moves her mouth while her line appears in the conversation.
        if isinstance(text, str) and text.lower().startswith('helena:') and hasattr(self, 'hud'):
            dur = max(900, min(4200, len(text) * 38))
            self.hud.speaking = True
            self.hud.state = 'SPEAKING'
            if hasattr(self, '_voice_wave'):
                self._voice_wave.set_state('SPEAKING')
            QTimer.singleShot(dur, lambda: self._apply_state('LISTENING' if not self._muted else 'MUTED'))

    def _clear_system_log(self):
        if hasattr(self, '_system_console'):
            self._system_console.clear()
            self._append_system_log("SYSTEM: LOG limpiado")

    def _copy_system_log(self):
        if hasattr(self, '_system_console'):
            QApplication.clipboard().setText(self._system_console.toPlainText())
            self._append_system_log("SYSTEM: LOG copiado al portapapeles")

    def _save_system_log(self):
        if not hasattr(self, '_system_console'):
            return
        default = BASE_DIR / "logs" / f"helena_system_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Guardar LOG del sistema", str(default), "Log (*.txt *.log);;Todos (*.*)")
        if path:
            Path(path).write_text(self._system_console.toPlainText(), encoding="utf-8")
            self._append_system_log(f"SYSTEM: LOG guardado en {Path(path).name}")

    def _set_code_all(self, code: str):
        if hasattr(self, '_lab_big'):
            self._lab_big.set_code(code)

    def open_code_file(self, path: str):
        if hasattr(self, '_lab_big'):
            self._switch_page("CODE LAB")
            self._lab_big.set_file(path)
            self._append_log(f"SYSTEM: archivo abierto en CODE LAB: {Path(path).name}")

    def set_code_file(self, path: str, code: str):
        if hasattr(self, '_lab_big'):
            self._switch_page("CODE LAB")
            self._lab_big.set_file(path, code)
            self._append_log(f"SYSTEM: archivo sincronizado en CODE LAB: {Path(path).name}")

    def save_code_file(self) -> str:
        if hasattr(self, '_lab_big'):
            self._lab_big.save_code()
            return "CODE LAB guardado."
        return "CODE LAB no disponible."

    def get_code_context(self) -> dict:
        if not hasattr(self, '_lab_big'):
            return {}
        lab = self._lab_big
        return {
            "code": lab.get_code(),
            "file_path": str(lab._current_path) if getattr(lab, "_current_path", None) else "",
            "language": lab._lang.currentText().lower(),
        }

    def _strip_code_fence_for_lab(self, code: str) -> str:
        text = str(code or "").strip()
        if not text.startswith("```") or text.count("```") < 2:
            return text
        parts = text.split("```")
        block = parts[1] if len(parts) > 1 else text
        lines = block.splitlines()
        if lines and len(lines[0].strip()) < 24 and not any(ch in lines[0] for ch in "=(){};:"):
            lines = lines[1:]
        return "\n".join(lines).strip()

    def _build_code_lab_text_first_prompt(self, code: str) -> str:
        context = self.get_code_context()
        raw_code = self._strip_code_fence_for_lab(code)
        language = context.get("language") or "desconocido"
        file_path = context.get("file_path") or "buffer sin ruta"
        lines = raw_code.splitlines()
        line_count = len(lines)

        header = f"""[CODE LAB / TEXT FIRST]
MODO CODE LAB: responde texto primero.
Usa text_output con target=hud para dejar la explicacion completa en el HUD / CODE LAB / SYSTEM.
Si vas a modificar, crear, optimizar, ejecutar o probar archivos reales, usa code_helper.
No digas "me pongo a trabajar" como resultado final: confirma con CODE LAB RESULT indicando accion, estado, archivo, backup y audit receipt.
Si solo analizaste y no cambiaste archivos, decilo explicitamente.
Para autodesarrollo de Helena, solo edita archivos si el usuario lo pidio claramente y usa allow_self_edit=true.
La voz local del HUD debe ser una sola frase breve, por ejemplo: "Listo usuario, te deje el analisis en el HUD."
Si Helena esta hablando por Discord, podes dar un resumen oral un poco mas natural, pero igual breve.
No leas el codigo completo en voz y no recites bloques largos de codigo salvo que el usuario lo pida explicitamente.
Si el analisis es largo, dividilo en secciones de texto: estructura, problemas, riesgos y proximos pasos.
Antes de seguir hablando mucho, pregunta: "sigo con el siguiente bloque?"

Archivo: {file_path}
Lenguaje: {language}
Lineas: {line_count}
Caracteres: {len(raw_code)}
Pedido del usuario: explicame este codigo y ayudame."""

        if len(raw_code) <= 3000:
            return header + "\n\nCodigo enviado desde CODE LAB:\n```" + language + "\n" + raw_code + "\n```"

        first = "\n".join(lines[:90]).strip()
        last = "\n".join(lines[-90:]).strip() if line_count > 90 else ""
        return header + f"""

El codigo supera 3000 caracteres. No lo trates como una sola masa para voz.
Analiza por partes usando este contexto resumido y, si necesitas mas detalle, pedile al usuario el siguiente bloque.

Fragmento inicial:
```{language}
{first}
```

Fragmento final:
```{language}
{last}
```
"""

    def _send_code_from_lab(self, code: str):
        self._append_log("USUARIO: [Codigo enviado desde CODE LAB]")
        if self.on_text_command:
            prompt = self._build_code_lab_text_first_prompt(code)
            threading.Thread(target=self.on_text_command, args=(prompt,), daemon=True).start()
        return

    def _on_project_selected(self, path: str):
        p = Path(path)
        label = p.name if p.name else str(p)
        self._file_hint.setText(f"PROJECT: {label[:34]}")
        self._append_log(f"SYSTEM: proyecto cargado: {label}")

    def _send_project_summary(self, summary: str):
        self._append_log("USUARIO: [Proyecto enviado desde PROJECT FILES]")
        if self.on_text_command:
            prompt = "Revisá esta estructura de proyecto y orientame paso a paso:\n\n" + summary
            threading.Thread(target=self.on_text_command, args=(prompt,), daemon=True).start()

    def _quick_file_action(self, action: str):
        action = (action or "").upper()
        try:
            if action == "NOTES":
                self._switch_page("CODE LAB")
                note = BASE_DIR / "memory" / "helena_notes.md"
                if not note.exists():
                    note.parent.mkdir(parents=True, exist_ok=True)
                    note.write_text("# HELENA NOTES\n\n", encoding="utf-8")
                self._lab_big.set_code(note.read_text(encoding="utf-8"))
                self._append_log("SYSTEM: Quick Files > NOTES abierto en CODE LAB")
            elif action == "SCRIPTS":
                path, _ = QFileDialog.getOpenFileName(self, "Abrir script", str(BASE_DIR), "Código (*.py *.js *.ts *.java *.cpp *.cs *.html *.css *.json *.sql *.sh);;Todos (*.*)")
                if path:
                    self._switch_page("CODE LAB")
                    self._lab_big.set_code(Path(path).read_text(encoding="utf-8", errors="ignore"))
                    self._append_log(f"FILE: script cargado: {Path(path).name}")
            elif action == "MEDIA":
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Cargar archivo multimedia o documento",
                    str(Path.home()),
                    "Multimedia y documentos (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.svg *.ico *.mp3 *.wav *.ogg *.m4a *.aac *.flac *.opus *.mp4 *.mov *.mkv *.webm *.avi *.pdf *.docx *.doc *.pptx *.xlsx *.csv *.json *.txt *.md);;Imágenes (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.svg *.ico);;Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac *.opus);;Video (*.mp4 *.mov *.mkv *.webm *.avi);;Documentos (*.pdf *.docx *.doc *.pptx *.xlsx *.csv *.json *.txt *.md);;Todos (*.*)"
                )
                if path:
                    self._on_file_selected(path)
                    self._append_log(f"SYSTEM: Quick Files > MEDIA cargado: {Path(path).name}")
            elif action == "DATA":
                path, _ = QFileDialog.getOpenFileName(self, "Cargar archivo de datos", str(Path.home()), "Datos (*.json *.csv *.txt *.md *.xml *.xlsx);;Todos (*.*)")
                if path:
                    self._on_file_selected(path)
            elif action == "LOGS":
                self._switch_page("SYSTEM")
                if hasattr(self, '_system_console'):
                    self._system_console.append("[LOG] Vista de diagnóstico abierta desde Quick Files")
                self._append_log("SYSTEM: Quick Files > LOGS abierto")
            elif action == "PROFILE":
                self._switch_page("SYSTEM")
                if hasattr(self, '_system_console'):
                    self._system_console.append("[PROFILE] HELENA Core v6.3\n[PROFILE] Mode: Emotional / Learning Companion\n[PROFILE] Rig: front-calibration pending final transparent frontal asset")
                self._append_log("SYSTEM: perfil de HELENA abierto")
            elif action == "CONFIG":
                self._switch_page("CODE LAB")
                cfg = API_FILE if API_FILE.exists() else (CONFIG_DIR / "api_keys.example.json")
                if cfg.exists():
                    self._lab_big.set_code(cfg.read_text(encoding="utf-8", errors="ignore"))
                    self._append_log(f"SYSTEM: Config abierto: {cfg.name}")
                else:
                    self._lab_big.set_code('{\n  "gemini_api_key": "",\n  "openrouter_api_key": "",\n  "os_system": "windows"\n}')
                    self._append_log("SYSTEM: plantilla config creada en CODE LAB")
        except Exception as e:
            self._append_log(f"ERROR: Quick Files {action}: {e}")

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._append_log(f"USUARIO: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _on_file_selected(self, path: str):
        self._current_file = path
        p = Path(path)
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"ARCHIVO ACTIVO: {p.name[:28]} - {size}")
        self._append_log(f"FILE: {p.name} ({size}) cargado")
        if self.on_text_command:
            msg = f"[FILE_UPLOADED] path={path} | name={p.name} | size={size}. Decime brevemente que podés ver el archivo y preguntame qué quiero hacer."
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        self._apply_state("MUTED" if self._muted else "LISTENING")
        self._append_log("SYSTEM: micrófono silenciado" if self._muted else "SYSTEM: micrófono activo")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("MUTE")
            self._mute_btn.setStyleSheet(f"QPushButton{{background:#18030a;color:{C.MUTED_C};border:1px solid {C.MUTED_C};border-radius:7px;}}")
        else:
            self._mute_btn.setText("MIC")
            self._mute_btn.setStyleSheet(f"QPushButton{{background:#03121d;color:{C.GREEN};border:1px solid {C.BORDER_A};border-radius:7px;}} QPushButton:hover{{border:1px solid {C.PRI};}}")

    def _apply_state(self, state: str):
        normalized = {
            "ESCUCHANDO":"LISTENING", "LISTENING":"LISTENING", "SPEAKING":"SPEAKING",
            "THINKING":"THINKING", "PENSANDO":"THINKING", "PROCESANDO":"THINKING",
            "MUTED":"MUTED"
        }.get(state, state)
        self.hud.state = normalized
        self.hud.speaking = (normalized == "SPEAKING")
        if hasattr(self, '_voice_wave'):
            self._voice_wave.set_state(normalized)
        if hasattr(self, '_footer_labels'):
            self._footer_labels['VOICE'].setText("MUTED" if normalized == "MUTED" else normalized)

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            # OpenRouter es opcional: sirve como apoyo/free tier, pero Helena puede arrancar con Gemini.
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget(); ow, oh = 460, 430
        ov.setGeometry((cw.width()-ow)//2, (cw.height()-oh)//2, ow, oh)
        ov.done.connect(self._on_setup_done)
        ov.show(); self._overlay = ov

    def _on_setup_done(self, key: str, or_key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {}
        if API_FILE.exists():
            try:
                data = json.loads(API_FILE.read_text(encoding="utf-8-sig"))
            except Exception:
                data = {}
        # IMPORTANTE: merge, no overwrite. Así no se pierden Discord, memoria ni políticas de costo.
        data["gemini_api_key"] = key
        if or_key:
            data["openrouter_api_key"] = or_key
        elif "openrouter_api_key" not in data:
            data["openrouter_api_key"] = ""
        data["os_system"] = os_name
        API_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        self._ready = True
        if self._overlay:
            self._overlay.hide(); self._overlay = None
        self._apply_state("LISTENING")
        self._append_log(f"SYSTEM: Initialised. OS={os_name.upper()}. HELENA online.")


class _HelenaConsoleTee:
    """Duplica stdout/stderr: consola real + pestaña SYSTEM LOG del HUD."""
    def __init__(self, original, emit_func, prefix: str = ""):
        self._original = original
        self._emit = emit_func
        self._prefix = prefix
        self._buf = ""
        self._helena_tee = True

    def write(self, data):
        try:
            self._original.write(data)
        except Exception:
            pass
        if not isinstance(data, str):
            data = str(data)
        self._buf += data
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip("\r")
            if line.strip():
                try:
                    self._emit(self._prefix + line)
                except Exception:
                    pass
        return len(data)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        if self._buf.strip():
            line = self._buf.rstrip("\r\n")
            self._buf = ""
            try:
                self._emit(self._prefix + line)
            except Exception:
                pass

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class HelenaUI:
    def __init__(self, face_path: str, size=None):
        _set_windows_app_user_model_id()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        try:
            app_icon = _helena_icon()
            if not app_icon.isNull():
                self._app.setWindowIcon(app_icon)
        except Exception:
            pass
        try:
            self._app.setQuitOnLastWindowClosed(False)
        except Exception:
            pass
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)
        self._install_system_console_tee()

    def _install_system_console_tee(self):
        def emit(line: str):
            try:
                self._win._syslog_sig.emit(line)
            except Exception:
                pass
        if not getattr(sys.stdout, '_helena_tee', False):
            sys.stdout = _HelenaConsoleTee(sys.stdout, emit)
        if not getattr(sys.stderr, '_helena_tee', False):
            sys.stderr = _HelenaConsoleTee(sys.stderr, emit)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return getattr(self._win, '_current_file', None)

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)
        code = self._extract_code_block(text)
        if code:
            self._win._code_sig.emit(code)

    def set_code(self, code: str):
        self._win._code_sig.emit(code)

    def get_code(self) -> str:
        if getattr(self._win, "_active_page", "CORE") == "CODE LAB" and hasattr(self._win, "_lab_big"):
            return self._win._lab_big.get_code()
        return self._win._code_lab.get_code()

    def _extract_code_block(self, text: str) -> str:
        if not isinstance(text, str) or "```" not in text:
            return ""
        parts = text.split("```")
        if len(parts) < 3:
            return ""
        block = parts[1]
        lines = block.splitlines()
        if lines and len(lines[0].strip()) < 18 and not any(ch in lines[0] for ch in "=(){};:"):
            lines = lines[1:]
        return "\n".join(lines).strip()

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("ESCUCHANDO")
