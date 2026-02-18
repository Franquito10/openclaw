import os, time, json, datetime, subprocess, shutil
import requests

BASE = os.path.expanduser("~/workspace")
INBOX = os.path.join(BASE, "inbox")
OUT = os.path.join(BASE, "outputs")
LOGS = os.path.join(BASE, "logs")
STATE_DIR = os.path.join(BASE, "state")
MEMORY_PATH = os.path.join(STATE_DIR, "memory.json")

os.makedirs(INBOX, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

# === “Cerebro” ===
# Por defecto usa Ollama. Si detecta CLI de Claude (o lo que definas), lo usa.
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = os.environ.get("CONDUCTOR_OLLAMA_MODEL", "llama3.1:8b")

# Si existe un CLI llamado "claude" en PATH, lo intentamos usar como backend opcional.
USE_CLAUDE_CLI = bool(shutil.which("claude")) and os.environ.get("CONDUCTOR_BRAIN", "").lower() == "claude"


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg: str):
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    with open(os.path.join(LOGS, "conductor.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_memory() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return {"created_tasks": [], "last_goal": "", "notes": []}
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"created_tasks": [], "last_goal": "", "notes": []}


def save_memory(mem: dict):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


def ollama(prompt: str) -> str:
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    r = requests.post(OLLAMA_URL, json=payload, timeout=600)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def claude_cli(prompt: str) -> str:
    """
    Backend opcional. Requiere que exista un comando 'claude' en PATH y credenciales configuradas.
    Si falla, se vuelve a Ollama.
    """
    try:
        # Nota: este comando puede variar según instalación. Lo dejamos minimalista.
        # Si tu CLI usa otro comando, lo adaptamos en 30s.
        p = subprocess.run(
            ["claude", "-p", prompt],
            check=True,
            capture_output=True,
            text=True,
        )
        return (p.stdout or "").strip()
    except Exception as e:
        log(f"WARNING: Claude CLI failed, fallback to Ollama. Reason: {e}")
        return ollama(prompt)


def brain(prompt: str) -> str:
    if USE_CLAUDE_CLI:
        return claude_cli(prompt)
    return ollama(prompt)


def ts_slug():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def write_inbox_task(name_prefix: str, content: str) -> str:
    """
    Crea una tarea nueva en INBOX. No la marca .done (eso lo hace agent_mvp).
    """
    fname = f"{name_prefix}__{ts_slug()}.txt"
    path = os.path.join(INBOX, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    return path


def parse_json_safely(text: str) -> dict:
    # intenta extraer JSON aunque el modelo devuelva texto extra
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return {}


def build_subtasks(goal: str) -> list[dict]:
    """
    Devuelve una lista de subtareas estructuradas.
    """
    prompt = f"""
Sos el ORQUESTADOR de un sistema de agentes en WSL.

Objetivo del usuario:
{goal}

Contexto REAL:
- inbox: {INBOX} (el ejecutor consume .txt)
- outputs: {OUT} (el ejecutor escribe .md)
- logs: {LOGS}
- El ejecutor entiende 'STRICT:' para respuestas exactas.

Tarea:
Generá un plan en JSON con máximo 6 subtareas.
Cada subtarea debe tener:
- id (string corto)
- title (corto)
- prompt (texto exacto que se escribirá en el .txt para el ejecutor)
- strict (true/false)

Reglas:
- No inventes herramientas externas.
- Prompts listos para copiar/pegar.
- Si 'strict' es true, el prompt debe empezar con 'STRICT:'.

Devolvé SOLO JSON.
""".strip()

    raw = brain(prompt)
    data = parse_json_safely(raw)

    tasks = data.get("tasks") or data.get("subtasks") or []
    if not isinstance(tasks, list):
        return []

    # normalización mínima
    cleaned = []
    for t in tasks[:6]:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or f"t{len(cleaned)+1}")
        title = str(t.get("title") or tid)
        strict = bool(t.get("strict"))
        tp = str(t.get("prompt") or "").strip()
        if strict and not tp.upper().startswith("STRICT:"):
            tp = "STRICT: " + tp
        if tp:
            cleaned.append({"id": tid, "title": title, "prompt": tp, "strict": strict})
    return cleaned


def main():
    log("Conductor started. Watching inbox for GOAL_*.txt ...")
    mem = load_memory()

    while True:
        # Convención: archivos GOAL_*.txt son “tareas madre” para el conductor
        goals = sorted(
            f for f in os.listdir(INBOX)
            if f.startswith("GOAL_") and f.endswith(".txt")
        )

        for g in goals:
            goal_path = os.path.join(INBOX, g)
            try:
                with open(goal_path, "r", encoding="utf-8") as f:
                    goal = f.read().strip()
            except Exception as e:
                log(f"ERROR reading goal {g}: {e}")
                continue

            log(f"Picked goal: {g}")
            mem["last_goal"] = goal

            subtasks = build_subtasks(goal)
            if not subtasks:
                log("No subtasks generated (model returned empty/invalid JSON).")
                # marcamos goal como done para no loop infinito
                os.replace(goal_path, goal_path + ".done")
                continue

            created = []
            for st in subtasks:
                # prefijo con ID para trazabilidad
                p = write_inbox_task(f"{st['id']}_{st['title']}".replace(" ", "_"), st["prompt"])
                created.append(p)
                log(f"Created subtask -> {p}")

            mem["created_tasks"].append({
                "goal_file": g,
                "goal": goal,
                "created_at": now_iso(),
                "subtasks": created
            })
            save_memory(mem)

            # marcar el GOAL como done (lo maneja el conductor)
            os.replace(goal_path, goal_path + ".done")
            log(f"Goal marked done -> {goal_path}.done")

        time.sleep(2)


if __name__ == "__main__":
    main()
