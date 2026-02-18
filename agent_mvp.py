import os, time, datetime
import requests
import subprocess
import shutil
import re

BASE = os.path.expanduser("~/workspace")
INBOX = os.path.join(BASE, "inbox")
OUT = os.path.join(BASE, "outputs")
LOGS = os.path.join(BASE, "logs")
APPROVALS = os.path.join(BASE, "approvals")

os.makedirs(INBOX, exist_ok=True)
os.makedirs(OUT, exist_ok=True)
os.makedirs(LOGS, exist_ok=True)
os.makedirs(APPROVALS, exist_ok=True)

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = os.environ.get("AGENT_OLLAMA_MODEL", "llama3.1:8b")

# Backend opcional: Claude CLI si existe y AGENT_BRAIN=claude
USE_CLAUDE_CLI = bool(shutil.which("claude")) and os.environ.get("AGENT_BRAIN", "").lower() == "claude"
NEXT_RE = re.compile(r"^\s*NEXT:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

def claude_cli(prompt: str) -> str:
    try:
        p = subprocess.run(
            ["claude", "-p", prompt],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
        return (p.stdout or "").strip()
    except Exception as e:
        log(f"WARNING: Claude CLI failed, fallback to Ollama. Reason: {e}")
        return ollama(prompt)


def brain(prompt: str) -> str:
    if USE_CLAUDE_CLI:
        return claude_cli(prompt)
    return ollama(prompt)



def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def log(msg: str):
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(LOGS, "agent_mvp.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def detect_role(text: str) -> str:
    t = (text or "").lstrip()
    m = re.match(r"^@([a-zA-Z0-9_-]+)\s*:", t)
    if not m:
        return "pm"  # default
    return m.group(1).lower()

def strip_role_prefix(text: str) -> str:
    return re.sub(r"^@[a-zA-Z0-9_-]+\s*:\s*", "", (text or "").lstrip(), count=1)

def write_inbox_task(inbox_dir: str, name: str, text: str) -> str:
    # name sin .txt => lo agregamos
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "tarea"))
    if not safe.endswith(".txt"):
        safe += ".txt"
    full = os.path.join(inbox_dir, safe)

    # evitar pisar
    if os.path.exists(full):
        base, ext = os.path.splitext(safe)
        i = 2
        while True:
            alt = os.path.join(inbox_dir, f"{base}_{i}{ext}")
            if not os.path.exists(alt):
                full = alt
                safe = os.path.basename(alt)
                break
            i += 1

    with open(full, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")
    return safe
def extract_next_tasks(text: str) -> list[tuple[str, str]]:
    """
    Soporta:
    - NEXT: archivo.txt
    - NEXT: archivo.txt | @rol: texto...
    """
    out = []
    if not text:
        return out

    for m in NEXT_RE.finditer(text):
        line = (m.group(1) or "").strip()
        if not line:
            continue

        if "|" in line:
            name, body = [x.strip() for x in line.split("|", 1)]
            if not body:
                body = "@pm: (sin contenido)\n"
            out.append((name, body))
        else:
            # si solo viene el nombre, creamos una tarea placeholder
            out.append((line, "@pm: (tarea generada por NEXT, completá el contenido)\n"))

    # límite anti-caos
    return out[:10]

def materialize_next_tasks(answer: str):
    tasks = extract_next_tasks(answer)
    if not tasks:
        return

    for name, body in tasks:
        created = write_inbox_task(INBOX, name, body)
        log(f"NEXT materialized -> {created}")
def now_tag():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")

def run_cmd(cmd: str, cwd: str | None = None) -> tuple[int, str]:
    p = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    out = ""
    if p.stdout:
        out += p.stdout
    if p.stderr:
        out += ("\n" if out else "") + p.stderr
    return p.returncode, out.strip()


def ollama(prompt: str) -> str:
    payload = {"model": MODEL, "prompt": prompt, "stream": False}
    r = requests.post(OLLAMA_URL, json=payload, timeout=600)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def process_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        task = f.read().strip()

    strict = task.strip().upper().startswith("STRICT:")
    task_clean = task.split(":", 1)[1].strip() if strict else task

    log(f"Task picked: {os.path.basename(path)}")

    # --- EXEC MODE (aprobación humana) ---
    if task_clean.strip().upper().startswith("EXEC:"):
        cmd = task_clean.split(":", 1)[1].strip()
        base_name = os.path.splitext(os.path.basename(path))[0]
        approval_name = base_name + ".ok"
        approval_path = os.path.join(APPROVALS, approval_name)

        # Si no existe el OK, dejamos un pending y salimos (sin spamear)
        if not os.path.exists(approval_path):
            already = [
                x for x in os.listdir(OUT)
                if x.startswith(base_name + "__") and x.endswith("__PENDING.md")
            ]
            if already:
                log(f"PENDING already exists -> {already[-1]}")
                return

            pending_path = os.path.join(OUT, base_name + f"__{ts()}__PENDING.md")
            with open(pending_path, "w", encoding="utf-8") as f2:
                f2.write("PENDING APPROVAL\n\n")
                f2.write(f"Create this file to approve:\n{approval_path}\n\n")
                f2.write("Command to run:\n")
                f2.write(cmd + "\n")
            log(f"PENDING approval -> {pending_path}")
            return

        # Aprobado: ejecutamos
        rc, output = run_cmd(cmd, cwd=BASE)
        out_name = base_name + f"__{ts()}__EXEC.md"
        out_path = os.path.join(OUT, out_name)
        with open(out_path, "w", encoding="utf-8") as f2:
            f2.write(f"CMD:\n{cmd}\n\nEXIT_CODE: {rc}\n\nOUTPUT:\n{output}\n")
        log(f"EXEC done -> {out_path}")

        # marcar done y cortar (no llamar a Ollama)
        done_path = path + ".done"
        try:
            os.replace(path, done_path)
            log(f"Marked done -> {done_path}")
        except FileNotFoundError:
            log(f"WARNING: input file already moved/removed before marking done: {path}")

        log(f"Done -> {out_path}")
        return

    # --- NORMAL MODE (texto -> LLM -> output) ---
    context = f"""
Contexto REAL del proyecto (no inventar):
- Sistema: WSL2 Ubuntu en Windows 11
- Carpeta base: {BASE}
- Inbox: {INBOX} (tareas .txt entran acá)
- Outputs: {OUT} (resultados .md salen acá)
- Logs: {LOGS} (logs se guardan acá)
- Repo: {os.path.join(BASE, "repo")} (código)
- Venv: {os.path.join(BASE, "repo", ".venv")}
- Ollama API: http://127.0.0.1:11434 (modelo: {MODEL})

Reglas:
- Describí SOLO lo que hace ESTE script en ESTE proyecto.
- No inventes archivos/librerías.
- Entregá respuestas listas para copiar/pegar.
""".strip()

    if strict:
        prompt = f"""
Respondé EXACTAMENTE lo que la tarea pide, sin explicaciones, sin títulos, sin checklist, sin markdown extra.
Si la tarea pide una sola palabra, devolvé solo esa palabra.

Contexto:
- Inbox: {INBOX}
- Outputs: {OUT}
- Modelo: {MODEL}

Tarea:
{task_clean}
""".strip()
    else:
        prompt = f"""
Sos un agente ejecutor. Usá el contexto y respondé en español.

{context}

Tarea:
{task_clean}

Entregá:
1) Resultado final en Markdown (listo para usar)
2) Checklist de verificación
""".strip()

    answer = brain(prompt)

        # ✅ Handoff automático: si el output contiene NEXT:, crea nuevas tareas en inbox
    try:
        materialize_next_tasks(answer)
    except Exception as e:
        log(f"WARNING: NEXT materialize failed: {e}")


    out_name = os.path.splitext(os.path.basename(path))[0] + f"__{ts()}.md"
    out_path = os.path.join(OUT, out_name)
    with open(out_path, "w", encoding="utf-8") as f2:
        f2.write(answer + "\n")

    done_path = path + ".done"
    try:
        os.replace(path, done_path)
        log(f"Marked done -> {done_path}")
    except FileNotFoundError:
        log(f"WARNING: input file already moved/removed before marking done: {path}")

    log(f"Done -> {out_path}")


def main():
    log("Agent MVP started. Watching inbox...")
    try:
        while True:
            files = [
                os.path.join(INBOX, x)
                for x in os.listdir(INBOX)
                if x.endswith(".txt") and not x.startswith("GOAL_")
            ]
            for fp in sorted(files):
                try:
                    process_file(fp)
                except Exception as e:
                    log(f"ERROR processing {fp}: {e}")
            time.sleep(3)
    except KeyboardInterrupt:
        log("Agent MVP stopped by user (Ctrl+C).")


if __name__ == "__main__":
    main()
