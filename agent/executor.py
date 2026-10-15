import json
import re
import sys
import threading
import subprocess
import tempfile
import os
import time
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    import google.generativeai as genai

    if speak:
        speak("Estoy escribiendo código personalizado para esta tarea.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "You are an expert Python developer. "
            "Write clean, complete, working Python code. "
            "Use standard library + common packages. "
            "Install missing packages with subprocess + pip if needed. "
            "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
            f"SYSTEM PATHS:\n"
            f"  Desktop   = r'{desktop}'\n"
            f"  Downloads = r'{downloads}'\n"
            f"  Documents = r'{documents}'\n"
            f"  Home      = r'{home}'\n"
        )
    )

    try:
        response = model.generate_content(
            f"Write Python code to accomplish this task:\n\n{description}"
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        print(f"[Ejecutor] 🐍 Ejecutando código generado: {tmp_path}")

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=120, cwd=str(Path.home())
        )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode == 0 and output:
            return output
        elif result.returncode == 0:
            return "Tarea completada correctamente."
        elif error:
            raise RuntimeError(f"Code error: {error[:400]}")
        return "Completado."

    except subprocess.TimeoutExpired:
        raise RuntimeError("El código generado superó el límite de 120 segundos.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"El código generado falló: {e}")

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completado.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print(f"[Ejecutor] 💉 Contenido inyectado y traducido")

    return params
def _detect_language(text: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    try:
        response = model.generate_content(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        target_lang = _detect_language(goal)
        print(f"[Executor] 🌐 Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip()
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Ejecutor] ⚠️ Falló la traducción: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    elif tool == "cmd_control":
        from actions.cmd_control import cmd_control
        return cmd_control(parameters=parameters, player=None) or "Done."

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    elif tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("generated_code requires a 'description' parameter.")
        return _run_generated_code(description, speak=speak)

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    else:
        print(f"[Ejecutor] ⚠️ Herramienta desconocida '{tool}' — falling back to generated_code")
        return _run_generated_code(f"Accomplish this task: {parameters}", speak=speak)

class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Ejecutor] 🎯 Objetivo: {goal}")

        replan_intentos = 0
        completed_steps = []
        step_results    = {}
        plan            = create_plan(goal)

        while True:
            steps = plan.get("steps", [])

            if not steps:
                msg = "No pude crear un plan válido para esta tarea."
                if speak: speak(msg)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Tarea cancelada.")
                    return "Tarea cancelada."

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Ejecutor] ▶️ Paso {step_num}: [{tool}] {desc}")

                intento = 1
                step_ok = False

                while intento <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        tool_started = time.perf_counter()
                        result = _call_tool(tool, params, speak)
                        print(
                            f"[ToolTiming] tool={tool} step={step_num} "
                            f"elapsed_ms={(time.perf_counter() - tool_started) * 1000:.1f} outcome=ok"
                        )
                        step_results[step_num] = result
                        completed_steps.append(step)
                        print(f"[Ejecutor] ✅ Paso {step_num} completado: {str(result)[:100]}")
                        step_ok = True
                        break

                    except Exception as e:
                        error_msg = str(e)
                        print(f"[Ejecutor] ❌ Paso {step_num} intento {intento} falló: {error_msg}")
                        print(
                            f"[ToolTiming] tool={tool} step={step_num} "
                            f"elapsed_ms={(time.perf_counter() - tool_started) * 1000:.1f} "
                            f"outcome=error error_type={type(e).__name__}"
                        )

                        recovery = analyze_error(step, error_msg, attempt=intento)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            intento += 1
                            time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Ejecutor] ⏭️ Saltando paso {step_num}")
                            completed_steps.append(step)
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Tarea abortada. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return msg

                        else:
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion and tool != "generated_code":
                                try:
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    if speak: speak("Voy a probar un enfoque alternativo.")
                                    res = _call_tool(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak
                                    )
                                    step_results[step_num] = res
                                    completed_steps.append(step)
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print(f"[Executor] ⚠️ Fix falló: {fix_err}")

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            if success:
                return self._summarize(goal, completed_steps, speak)

            if replan_intentos >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"La tarea falló después de {replan_intentos} intentos de replanteo."
                if speak: speak(msg)
                return msg

            if speak: speak("Estoy ajustando el enfoque.")

            replan_intentos += 1
            plan = replan(goal, completed_steps, failed_step, failed_error)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None) -> str:
        fallback = f"Listo. Completé {len(completed_steps)} pasos para: {goal[:60]}."
        try:
            import google.generativeai as genai
            genai.configure(api_key=_get_api_key())
            model     = genai.GenerativeModel(model_name="gemini-2.5-flash-lite")
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
            prompt    = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing what was accomplished. "
                "Address the user naturally in Spanish. Be direct and positive."
            )
            response = model.generate_content(prompt)
            summary  = response.text.strip()
            if speak: speak(summary)
            return summary
        except Exception:
            if speak: speak(fallback)
            return fallback