from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path


def _run(cmd: list[str], timeout: int = 12) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        return result.returncode, out.strip()
    except Exception as exc:
        return 1, str(exc)


def _powershell(script: str, timeout: int = 12) -> tuple[int, str]:
    return _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout)


def _open_uri(uri: str) -> str:
    if platform.system().lower() == "windows":
        subprocess.Popen(["cmd", "/c", "start", "", uri], shell=False)
        return f"Abriendo: {uri}"
    return "Esta accion esta implementada para Windows."


def _windows_security_status() -> str:
    code, out = _powershell(
        "try { Get-MpComputerStatus | Select-Object AMServiceEnabled,AntivirusEnabled,"
        "RealTimeProtectionEnabled,AntivirusSignatureLastUpdated,"
        "QuickScanAge,FullScanAge | ConvertTo-Json -Compress } "
        "catch { $_.Exception.Message }"
    )
    if code != 0:
        return f"No pude leer Windows Security: {out}"
    try:
        data = json.loads(out)
        lines = ["Windows Security / Defender:"]
        for key, value in data.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)
    except Exception:
        return out or "Windows Security no devolvio datos."


def _threat_report() -> str:
    code, out = _powershell(
        "try { $a=@(); "
        "$a += Get-MpThreat -ErrorAction SilentlyContinue | Select-Object ThreatName,SeverityID,CategoryID,DidThreatExecute; "
        "$a += Get-MpThreatDetection -ErrorAction SilentlyContinue | Select-Object ThreatName,ActionSuccess,Resources,InitialDetectionTime,LastThreatStatusChangeTime,ThreatStatusID; "
        "$a | ConvertTo-Json -Compress } catch { $_.Exception.Message }",
        timeout=20,
    )
    if code != 0:
        return f"No pude consultar amenazas: {out}"
    if "acceso denegado" in out.lower() or "access denied" in out.lower():
        return (
            "Defender no autorizo la lectura detallada de amenazas desde PowerShell en esta sesion. "
            "Puedo abrir Windows Security para ver el detalle, o ejecutarse con permisos elevados para reportarlo por consola."
        )
    if not out or out.strip() in ("", "[]", "null"):
        return "No hay amenazas activas reportadas por Microsoft Defender."
    try:
        data = json.loads(out)
        items = data if isinstance(data, list) else [data]
        lines = [f"Amenazas detectadas por Defender: {len(items)}"]
        for item in items[:10]:
            lines.append(
                f"- {item.get('ThreatName', 'Amenaza')} | accion_ok={item.get('ActionSuccess')} | "
                f"estado={item.get('ThreatStatusID')} | recurso={item.get('Resources')}"
            )
        if len(items) > 10:
            lines.append(f"... y {len(items) - 10} mas.")
        return "\n".join(lines)
    except Exception:
        return out


def _start_defender_scan(scan_type: str, path: str = "") -> str:
    scan_type = (scan_type or "quick").lower().strip()
    if scan_type in ("quick", "quick_scan"):
        ps = "Start-MpScan -ScanType QuickScan"
        label = "escaneo rapido"
        timeout = 900
    elif scan_type in ("full", "full_scan"):
        ps = "Start-MpScan -ScanType FullScan"
        label = "escaneo completo"
        timeout = 21600
    elif scan_type in ("custom", "custom_scan"):
        if not path:
            return "Para un escaneo personalizado necesito un path de archivo o carpeta."
        target = str(Path(path).expanduser())
        safe_target = target.replace("'", "''")
        ps = f"Start-MpScan -ScanType CustomScan -ScanPath '{safe_target}'"
        label = f"escaneo personalizado de {target}"
        timeout = 7200
    else:
        return "Tipo de escaneo desconocido. Usa quick_scan, full_scan o custom_scan."

    code, out = _powershell(f"try {{ {ps}; 'SCAN_FINISHED' }} catch {{ $_.Exception.Message }}", timeout=timeout)
    if code != 0 or "SCAN_FINISHED" not in out:
        return f"No pude completar el {label}: {out}"

    status = _windows_security_status()
    threats = _threat_report()
    return f"Termine el {label}.\n\n{status}\n\n{threats}"


def _list_processes(limit: int = 20) -> str:
    code, out = _powershell(
        f"Get-Process | Sort-Object CPU -Descending | Select-Object -First {int(limit)} "
        "Name,Id,CPU,WorkingSet | Format-Table -AutoSize | Out-String",
        timeout=10,
    )
    return out if code == 0 else f"No pude listar procesos: {out}"

def _kill_process(name: str = "", pid: str = "", force: bool = True) -> str:
    if platform.system().lower() != "windows":
        return "Cerrar procesos esta implementado para Windows."
    name = (name or "").strip()
    pid = str(pid or "").strip()
    force_flag = "-Force" if force else ""
    if pid:
        try:
            pid_int = int(pid)
        except ValueError:
            return f"PID invalido: {pid}"
        code, out = _powershell(
            f"try {{ Stop-Process -Id {pid_int} {force_flag} -ErrorAction Stop; 'OK' }} catch {{ $_.Exception.Message }}",
            timeout=10,
        )
        return f"Proceso PID {pid} cerrado." if code == 0 and "OK" in out else f"No pude cerrar PID {pid}: {out}"
    if not name:
        return "Necesito el nombre o PID del proceso a cerrar."
    safe = name.replace("'", "''").replace(".exe", "")
    code, out = _powershell(
        "$target='{safe}'; "
        "$procs=Get-Process | Where-Object {{ $_.ProcessName -like \"*$target*\" }}; "
        "if (-not $procs) {{ 'NOT_FOUND' }} else {{ $names=($procs | Select-Object -ExpandProperty ProcessName) -join ', '; "
        "$procs | Stop-Process {force_flag} -ErrorAction Stop; 'OK:' + $names }}".format(
            safe=safe,
            force_flag=force_flag,
        ),
        timeout=10,
    )
    if code == 0 and out.startswith("OK:"):
        return f"Proceso(s) cerrados: {out[3:]}"
    if "NOT_FOUND" in out:
        return f"No encontre procesos que coincidan con: {name}"
    return f"No pude cerrar {name}: {out}"


def _list_services(name: str = "") -> str:
    pattern = (name or "*").replace("'", "''")
    code, out = _powershell(
        f"Get-Service -Name '{pattern}' -ErrorAction SilentlyContinue | "
        "Select-Object Status,Name,DisplayName | Format-Table -AutoSize | Out-String",
        timeout=10,
    )
    return out if code == 0 and out.strip() else "No encontre servicios para ese filtro."


def _open_path(path: str) -> str:
    target = Path(path).expanduser()
    if not target.exists():
        return f"No existe: {target}"
    if platform.system().lower() == "windows":
        subprocess.Popen(["explorer", str(target)], shell=False)
        return f"Abriendo en Explorer: {target}"
    return f"Ruta existente: {target}"


def system_control(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).lower().strip()

    if player:
        player.write_log(f"[Sistema] {action}")

    blocked = {
        "disable_antivirus", "turn_off_antivirus", "disable_defender",
        "bypass_antivirus", "tamper_protection_off", "disable_firewall",
    }
    if action in blocked:
        return (
            "No puedo desactivar, evadir o debilitar antivirus/firewall. "
            "Puedo abrir el panel de seguridad, mostrar estado, revisar procesos y ayudarte con configuracion legitima."
        )

    if action in ("security_status", "defender_status", "antivirus_status"):
        return _windows_security_status()

    if action in ("quick_scan", "scan_quick", "antivirus_quick_scan"):
        return _start_defender_scan("quick")

    if action in ("full_scan", "scan_full", "antivirus_full_scan"):
        return _start_defender_scan("full")

    if action in ("custom_scan", "scan_path", "scan_file", "scan_folder"):
        return _start_defender_scan("custom", str(params.get("path", "")))

    if action in ("threats", "threat_report", "scan_results"):
        return _threat_report()

    if action in ("open_security", "open_windows_security", "open_antivirus"):
        return _open_uri("windowsdefender:")

    if action in ("open_settings", "settings"):
        return _open_uri("ms-settings:")

    if action in ("open_apps_settings", "apps_settings"):
        return _open_uri("ms-settings:appsfeatures")

    if action in ("open_startup_apps", "startup_apps"):
        return _open_uri("ms-settings:startupapps")

    if action in ("open_firewall", "firewall"):
        return _open_uri("windowsdefender://network")

    if action in ("processes", "list_processes"):
        return _list_processes(int(params.get("limit", 20)))

    if action in ("kill_process", "close_process", "end_process", "terminate_process"):
        return _kill_process(
            name=str(params.get("name", "") or params.get("process", "") or params.get("app_name", "")),
            pid=str(params.get("pid", "")),
            force=str(params.get("force", "true")).lower() in ("true", "1", "yes", "si", "sí"),
        )

    if action in ("services", "list_services"):
        return _list_services(str(params.get("name", "")))

    if action in ("open_path", "open_folder"):
        return _open_path(str(params.get("path", Path.home())))

    return (
        "Accion de sistema desconocida. Usa: security_status, open_security, "
        "quick_scan, full_scan, custom_scan, threats, open_settings, "
        "open_apps_settings, open_startup_apps, processes, services, open_path."
    )
