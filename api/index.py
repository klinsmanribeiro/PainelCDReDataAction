from flask import Flask, render_template, jsonify, request, Response, session, redirect, url_for
from datetime import datetime, timezone, timedelta
import os
import json
import requests
import time
from collections import deque
from dotenv import load_dotenv

load_dotenv()

# Em Vercel, api/index.py fica em /var/task/api/; templates estão em /var/task/templates/
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(_ROOT_DIR, "templates"))
app.secret_key = os.getenv("SECRET_KEY", "hsm-dashboard-super-secret-key")

# ─── AUTENTICAÇÃO ────────────────────────────────────────────────────────────
LOGIN_USER = os.getenv("LOGIN_USER", "")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "")

@app.before_request
def check_login():
    public_routes = ["login", "static", "debug_auth", "debug_connection", "login_genesys", "callback"]
    if request.endpoint not in public_routes and not session.get("logged_in"):
        # Rotas de API retornam JSON em vez de redirecionar (evita HTML em fetch())
        if request.path.startswith("/api/"):
            return jsonify({"error": "Sessão expirada. Faça login novamente.", "auth_required": True}), 401
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username")
        pw = request.form.get("password")
        if user == LOGIN_USER and pw == LOGIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="Usuário ou senha incorretos.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─── ROTAS DE AUTENTICAÇÃO GENESYS (OAUTH) ───────────────────────────────────

@app.route("/login-genesys")
def login_genesys():
    """Redireciona para o login da Genesys Cloud."""
    auth_url = f"https://login.{GENESYS_REGION}/oauth/authorize"
    params = {
        "client_id": GENESYS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI
    }
    from urllib.parse import urlencode
    return redirect(f"{auth_url}?{urlencode(params)}")

@app.route("/callback")
def callback():
    """Trata o retorno do OAuth e troca o código pelo token."""
    code = request.args.get("code")
    if not code:
        return "Código não fornecido", 400

    import base64
    auth_url = f"https://login.{GENESYS_REGION}/oauth/token"
    auth_header = base64.b64encode(f"{GENESYS_CLIENT_ID}:{GENESYS_CLIENT_SECRET}".encode()).decode()

    try:
        resp = requests.post(
            auth_url,
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
            headers={"Authorization": f"Basic {auth_header}"},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        access_token  = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        expires_in    = data.get("expires_in", 86400)

        # Atualiza cache e header global
        global _token_cache, HEADERS
        _token_cache = {"token": f"Bearer {access_token}", "expires_at": time.time() + expires_in}
        HEADERS["Authorization"] = f"Bearer {access_token}"

        if refresh_token:
            save_refresh_token(refresh_token)
            # Exibe o refresh_token para o usuário salvar no Vercel (apenas uma vez)
            return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Login Genesys OK</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:40px auto;padding:20px}}
pre{{background:#f4f4f4;padding:16px;border-radius:6px;word-break:break-all;white-space:pre-wrap}}
.btn{{display:inline-block;margin-top:16px;padding:10px 20px;background:#0070f3;color:#fff;border-radius:6px;text-decoration:none}}</style>
</head><body>
<h2>&#10003; Autenticação Genesys concluída!</h2>
<p>Salve o <strong>Refresh Token</strong> abaixo como variável de ambiente <code>GENESYS_REFRESH_TOKEN</code> no Vercel
(<em>Settings → Environment Variables</em>) para que o app renove o token automaticamente sem precisar fazer login novamente:</p>
<pre id="rt">{refresh_token}</pre>
<button onclick="navigator.clipboard.writeText(document.getElementById('rt').textContent)">Copiar</button>
<br><a class="btn" href="/">Ir para o Dashboard</a>
</body></html>"""

        return redirect(url_for("index"))
    except Exception as e:
        return f"Erro na autenticação OAuth: {str(e)}", 500

@app.route("/debug-auth")
def debug_auth():
    """Rota para validar configurações de autenticação em produção."""
    masked_client_id = f"{GENESYS_CLIENT_ID[:5]}..." if GENESYS_CLIENT_ID else "Não configurado"

    return jsonify({
        "status": "online",
        "region": GENESYS_REGION,
        "redirect_uri": REDIRECT_URI,
        "client_id": masked_client_id,
        "has_client_secret": bool(GENESYS_CLIENT_SECRET),
        "has_oauth_token": bool(os.getenv("OAUTH_TOKEN")),
        "has_login_user": bool(os.getenv("LOGIN_USER")),
        "has_refresh_token_disk": os.path.exists(REFRESH_TOKEN_FILE),
        "vercel_env": bool(os.environ.get("VERCEL")),
        "template_folder": app.template_folder,
    })


@app.route("/debug-connection")
def debug_connection():
    """Testa a conectividade com a API Genesys e retorna diagnóstico detalhado."""
    result = {
        "region": GENESYS_REGION,
        "base_url": BASE_URL,
        "has_client_id": bool(GENESYS_CLIENT_ID),
        "has_client_secret": bool(GENESYS_CLIENT_SECRET),
        "has_oauth_token": bool(os.getenv("OAUTH_TOKEN")),
        "vercel_env": bool(os.environ.get("VERCEL")),
        "token_status": None,
        "api_test": None,
        "error": None,
    }

    # Tenta obter token
    try:
        token = get_auth_token()
        if token:
            result["token_status"] = "ok" if not token.startswith("Bearer ") or len(token) > 10 else "vazio"
        else:
            result["token_status"] = "falhou - nenhum token obtido"
            result["error"] = "get_auth_token() retornou None. Verifique GENESYS_CLIENT_ID, GENESYS_CLIENT_SECRET ou OAUTH_TOKEN nas variáveis de ambiente do Vercel."
            return jsonify(result)
    except Exception as e:
        result["token_status"] = f"exceção: {str(e)}"
        result["error"] = str(e)
        return jsonify(result)

    # Testa um endpoint leve da Genesys
    try:
        test_resp = requests.get(
            f"{BASE_URL}/api/v2/users/me",
            headers=HEADERS,
            timeout=10,
        )
        result["api_test"] = {
            "status_code": test_resp.status_code,
            "ok": test_resp.status_code == 200,
        }
        if test_resp.status_code == 200:
            me = test_resp.json()
            result["api_test"]["user"] = me.get("name", "—")
            result["api_test"]["org"] = me.get("organization", {}).get("name", "—")
        elif test_resp.status_code == 401:
            result["error"] = "Token inválido ou expirado (401). Atualize OAUTH_TOKEN ou verifique as credenciais Client Credentials no Vercel."
        elif test_resp.status_code == 403:
            result["error"] = "Sem permissão (403). O OAuth client não tem os escopos necessários (analytics:conversationDetail:view)."
        else:
            result["error"] = f"Genesys retornou HTTP {test_resp.status_code}."
    except Exception as e:
        result["api_test"] = {"ok": False, "error": str(e)}
        result["error"] = f"Falha ao conectar na API Genesys: {str(e)}"

    return jsonify(result)

# ─── CONFIGURAÇÃO GENESYS & CDR ──────────────────────────────────────────────
GENESYS_REGION   = os.getenv("GENESYS_REGION", "sae1.pure.cloud")
BASE_URL         = f"https://api.{GENESYS_REGION}"
GENESYS_CLIENT_ID     = os.getenv("GENESYS_CLIENT_ID", "")
GENESYS_CLIENT_SECRET = os.getenv("GENESYS_CLIENT_SECRET", "")

# Redirecionamento para OAuth
DEFAULT_REDIRECT = "https://genesys-cdr.vercel.app/callback"
REDIRECT_URI     = os.getenv("REDIRECT_URI", DEFAULT_REDIRECT)
REFRESH_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "refresh_token.txt")

# Cache de tokens para evitar renovações excessivas
_token_cache = {"token": "", "expires_at": 0}

def _kv_get(key):
    """Lê um valor do Upstash KV."""
    kv_url   = os.environ.get("genesys_KV_REST_API_URL") or os.environ.get("KV_REST_API_URL")
    kv_token = os.environ.get("genesys_KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if not kv_url or not kv_token:
        return None
    try:
        r = requests.get(f"{kv_url}/get/{key}",
                         headers={"Authorization": f"Bearer {kv_token}"}, timeout=5)
        if r.status_code == 200:
            return r.json().get("result")
    except Exception:
        pass
    return None

def _kv_set(key, value):
    """Grava um valor no Upstash KV."""
    kv_url   = os.environ.get("genesys_KV_REST_API_URL") or os.environ.get("KV_REST_API_URL")
    kv_token = os.environ.get("genesys_KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    if not kv_url or not kv_token:
        return False
    try:
        r = requests.post(f"{kv_url}/set/{key}",
                          headers={"Authorization": f"Bearer {kv_token}"},
                          data=value, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def save_refresh_token(token):
    """Salva o refresh token na sessão, no KV (Vercel) e no disco (local)."""
    try:
        session['refresh_token'] = token
    except Exception:
        pass
    _kv_set("genesys_refresh_token", token)
    try:
        with open(REFRESH_TOKEN_FILE, "w") as f:
            f.write(token)
    except Exception as e:
        print(f"Erro ao salvar refresh_token em disco: {e}")

def load_refresh_token():
    """Carrega o refresh token: sessão → KV → disco → env var."""
    try:
        if session.get('refresh_token'):
            return session['refresh_token']
    except Exception:
        pass
    kv_val = _kv_get("genesys_refresh_token")
    if kv_val:
        return kv_val
    if os.path.exists(REFRESH_TOKEN_FILE):
        try:
            with open(REFRESH_TOKEN_FILE, "r") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass
    return os.getenv("GENESYS_REFRESH_TOKEN")

# Cabeçalhos globais inicializados vazios (serão preenchidos pelo get_token)
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": ""
}

PAGE_SIZE        = 50
RATE_LIMIT_RPM   = 10

def _exchange_token(grant_type, **extra_data):
    """Troca credenciais por access_token na Genesys. Retorna (access_token, expires_in, refresh_token)."""
    import base64
    auth_url = f"https://login.{GENESYS_REGION}/oauth/token"
    auth_header = base64.b64encode(f"{GENESYS_CLIENT_ID}:{GENESYS_CLIENT_SECRET}".encode()).decode()
    data = {"grant_type": grant_type, **extra_data}
    resp = requests.post(auth_url, data=data,
                         headers={"Authorization": f"Basic {auth_header}"}, timeout=15)
    resp.raise_for_status()
    d = resp.json()
    return d.get("access_token"), d.get("expires_in", 86400), d.get("refresh_token")


def get_auth_token():
    """Obtém token válido na ordem: cache → refresh_token → client_credentials → OAUTH_TOKEN estático."""
    global _token_cache, HEADERS
    now = time.time()

    # 1) Cache ainda válido
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        HEADERS["Authorization"] = _token_cache["token"]
        return _token_cache["token"]

    # 2) Refresh token (Authorization Code flow — renova sem interação do usuário)
    if GENESYS_CLIENT_ID and GENESYS_CLIENT_SECRET:
        rt = load_refresh_token()
        if rt:
            try:
                access, expires_in, new_rt = _exchange_token("refresh_token", refresh_token=rt)
                if access:
                    new_token = f"Bearer {access}"
                    _token_cache = {"token": new_token, "expires_at": now + expires_in}
                    HEADERS["Authorization"] = new_token
                    if new_rt:
                        save_refresh_token(new_rt)
                    print(f"Token renovado via refresh_token. Expira em {expires_in}s.")
                    return new_token
            except Exception as e:
                print(f"Falha ao usar refresh_token: {e}")

    # 3) Client Credentials (se o OAuth client suportar)
    if GENESYS_CLIENT_ID and GENESYS_CLIENT_SECRET:
        try:
            access, expires_in, _ = _exchange_token("client_credentials")
            if access:
                new_token = f"Bearer {access}"
                _token_cache = {"token": new_token, "expires_at": now + expires_in}
                HEADERS["Authorization"] = new_token
                print(f"Token renovado via client_credentials. Expira em {expires_in}s.")
                return new_token
        except Exception as e:
            print(f"Falha client_credentials: {e}")

    # 4) OAUTH_TOKEN estático do .env / Vercel env vars
    static_token = os.getenv("OAUTH_TOKEN") or os.getenv("API_TOKEN", "")
    if static_token:
        if not static_token.startswith("Bearer "):
            static_token = f"Bearer {static_token}"
        HEADERS["Authorization"] = static_token
        print("Usando OAUTH_TOKEN estático (pode estar expirado).")
        return static_token

    return None






# ─────────────────────────────────────────────────────────────────────────────

import threading

request_times  = deque()
rate_hits      = 0
_cdr_tasks_cache = {"data": None, "ts": 0}   # cache scan de 10 min

# ── Data Actions: caches e estado ─────────────────────────────────────────────
_data_actions_catalog_cache = {"data": None, "ts": 0}       # catálogo de ações (10 min)
_data_actions_scan_cache    = {"data": None, "ts": 0, "flow_id": None}  # último scan
_data_actions_health_cache  = {"results": None, "ts": 0}    # último health check
_health_check_interval      = 3 * 3600   # padrão: 3 horas (em segundos)
_health_check_thread        = None

if os.environ.get("VERCEL"):
    HISTORY_FILE = "/tmp/cdr_history.json"
else:
    HISTORY_FILE = os.path.join(os.path.dirname(__file__), "data", "cdr_history.json")

import zlib
import base64



def load_history():
    kv_url = os.environ.get("genesys_KV_REST_API_URL") or os.environ.get("KV_REST_API_URL")
    kv_token = os.environ.get("genesys_KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    
    if kv_url and kv_token:
        try:
            r = requests.get(f"{kv_url}/get/cdr_history", headers={"Authorization": f"Bearer {kv_token}"}, timeout=10)
            if r.status_code == 200:
                result = r.json().get("result")
                if not result: return {}
                
                # Tenta descompactar (zlib + base64)
                try:
                    compressed_data = base64.b64decode(result)
                    decompressed = zlib.decompress(compressed_data).decode('utf-8')
                    return json.loads(decompressed)
                except Exception:
                    # Se falhar a descompactação, tenta ler como JSON puro (suporte a dados antigos)
                    try: return json.loads(result)
                    except: return {}
        except Exception as e:
            print(f"Erro ao ler KV: {e}")
            return {}

    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_history(data_dict):
    # Proteção: se o dicionário estiver vazio e já houver dados no arquivo, não sobrescreve
    if not data_dict: return

    kv_url = os.environ.get("genesys_KV_REST_API_URL") or os.environ.get("KV_REST_API_URL")
    kv_token = os.environ.get("genesys_KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    
    if kv_url and kv_token:
        try:
            json_str = json.dumps(data_dict, ensure_ascii=False)
            # Compacta para economizar espaço no KV (limite de 1MB no free tier)
            compressed = zlib.compress(json_str.encode('utf-8'))
            val = base64.b64encode(compressed).decode('utf-8')
            
            r = requests.post(f"{kv_url}/set/cdr_history", headers={"Authorization": f"Bearer {kv_token}"}, data=val, timeout=10)
            if r.status_code != 200:
                print(f"Erro ao salvar KV HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"Erro ao gravar KV: {e}")
        return

    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erro local save_history: {e}")

def update_daily_snapshot(flow_id, calls):
    hist = load_history()
    # Se o load_history falhou totalmente, evitamos corromper o banco
    if not isinstance(hist, dict): hist = {}
    
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in hist:
        hist[today] = {}
    hist[today][flow_id] = calls
    
    # Manter apenas 7 dias para economizar espaço
    valid_dates = set((datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(8))
    for k in list(hist.keys()):
        if k not in valid_dates:
            del hist[k]
            
    save_history(hist)

def get_flow_history_diffs(flow_id, current_calls):
    hist = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    dates = sorted([d for d in hist.keys() if d != today])
    if not dates:
        return []
        
    timeline_dates = dates + [today]
    diffs = []
    
    for i in range(1, len(timeline_dates)):
        prev_date = timeline_dates[i-1]
        curr_date = timeline_dates[i]
        
        if prev_date != today and flow_id not in hist.get(prev_date, {}):
            continue
            
        prev_calls = hist.get(prev_date, {}).get(flow_id, [])
        curr_calls = hist.get(curr_date, {}).get(flow_id, []) if curr_date != today else current_calls
        
        # Usamos action_id como chave primária pois ele é o UUID da ação no Architect
        prev_map = {c.get("action_id"): c for c in prev_calls if c.get("action_id")}
        curr_map = {c.get("action_id"): c for c in curr_calls if c.get("action_id")}
        
        for aid, c in curr_map.items():
            if aid not in prev_map:
                diffs.append({"date": curr_date, "type": "added", "call": c})
            else:
                p = prev_map[aid]
                changes = []
                if p.get("label") != c.get("label"):
                    changes.append(f"Nome: {p.get('label')} -> {c.get('label')}")
                if p.get("parent_task") != c.get("parent_task"):
                    changes.append(f"Pasta: {p.get('parent_task')} -> {c.get('parent_task')}")
                
                if changes:
                    diffs.append({"date": curr_date, "type": "edited", "call": c, "details": "; ".join(changes)})
                
        for aid, c in prev_map.items():
            if aid not in curr_map:
                diffs.append({"date": curr_date, "type": "removed", "call": c})
                
    diffs.sort(key=lambda x: x["date"], reverse=True)
    return diffs

# ── Mapeamentos em português ──────────────────────────────────────────────────
DIR_MAP = {
    "inbound":  "Receptivo",
    "outbound": "Ativo",
    "unknown":  "Desconhecido",
}
DISC_MAP = {
    "endpoint":    "Encerrado pelo cliente",
    "client":      "Encerrado pelo agente",
    "transfer":    "Transferido",
    "timeout":     "Timeout",
    "system":      "Sistema",
    "peer":        "Par",
    "error":       "Erro",
    "other":       "Outro",
}
SEG_MAP = {
    "system":    "Sistema",
    "ivr":       "URA",
    "acd":       "Fila ACD",
    "interact":  "Atendimento",
    "hold":      "Espera",
    "wrapup":    "Pós-atendimento",
    "unknown":   "Desconhecido",
}
FLOW_TYPE_MAP = {
    "INBOUNDCALL":    "Receptivo Voz",
    "OUTBOUNDCALL":   "Ativo Voz",
    "INBOUNDSHORTMESSAGE": "SMS/WhatsApp Receptivo",
    "INBOUNDEMAIL":   "E-mail Receptivo",
    "WORKFLOW":       "Workflow",
    "DIGITALBOT":     "Bot Digital",
    "BOT":            "Bot",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_dt(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except:
        return ts

def fmt_duration(ms):
    """Milissegundos → mm:ss ou hh:mm:ss"""
    if not ms:
        return "—"
    try:
        s = int(ms) // 1000
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
    except:
        return "—"

def check_rate():
    global rate_hits
    now = time.time()
    while request_times and request_times[0] < now - 60:
        request_times.popleft()
    if len(request_times) >= RATE_LIMIT_RPM:
        rate_hits += 1
        return False, rate_hits, len(request_times)
    request_times.append(now)
    return True, rate_hits, len(request_times)

def genesys_error(resp):
    """Retorna mensagem de erro legível para códigos HTTP da Genesys."""
    codes = {
        400: "Requisição inválida (400): verifique os parâmetros enviados.",
        401: "Não autorizado (401): token inválido ou expirado.",
        403: "Sem permissão (403): verifique o escopo do token OAuth.",
        404: "Não encontrado (404): recurso inexistente.",
        408: "Timeout (408): Genesys demorou para responder.",
        429: "Rate limit da Genesys (429): aguarde antes de tentar novamente.",
        500: "Erro interno da Genesys (500).",
        503: "Genesys indisponível (503).",
    }
    return codes.get(resp.status_code, f"Erro HTTP {resp.status_code}.")


# ── Busca lista de flows ───────────────────────────────────────────────────────
def fetch_flows():
    flows = []
    page = 1
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/api/v2/flows",
                headers=HEADERS,
                params={"pageSize": 200, "pageNumber": page, "deleted": "false"},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"Erro ao buscar fluxos: HTTP {r.status_code} - {r.text}")
                break
            data = r.json()
            entities = data.get("entities", [])
            for e in entities:
                pub = e.get("publishedVersion") or e.get("checkedInVersion") or {}
                flows.append({
                    "id":              e.get("id", ""),
                    "name":            e.get("name", ""),
                    "type":            FLOW_TYPE_MAP.get(e.get("type", ""), e.get("type", "")),
                    "configurationUri": pub.get("configurationUri", ""),
                })
            if page >= data.get("pageCount", 1):
                break
            page += 1
        except Exception as e:
            print(f"Exceção ao buscar fluxos: {str(e)}")
            break
    return flows


# ── Escaneia fluxo em busca de Call Task CDR ──────────────────────────────────
def scan_flow_for_cdr_tasks(cfg_uri):
    """Retorna lista de CallTaskAction com taskName='CDR', com o nome da tarefa-pai."""
    calls = []
    try:
        r = requests.get(f"{BASE_URL}{cfg_uri}", headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return calls
        data = r.json()

        def walk(obj, task_ctx=None):
            if isinstance(obj, dict):
                # __type='Task' = definição de tarefa (pasta no Architect)
                if obj.get("__type") == "Task" and "name" in obj:
                    task_ctx = obj.get("name") or task_ctx

                if obj.get("__type") == "CallTaskAction" and obj.get("taskName") == "CDR":
                    label = "—"
                    for inp in obj.get("inputs", []):
                        lit = inp.get("value", {}).get("config", {}).get("lit", {})
                        if lit.get("text"):
                            label = lit["text"]
                            break
                        if inp.get("value", {}).get("text"):
                            label = inp["value"]["text"]
                            break
                    calls.append({
                        "action_id":   obj.get("id", ""),
                        "label":       label,
                        "tracking_id": obj.get("trackingId", ""),
                        "parent_task": task_ctx or "—",
                    })
                for v in obj.values():
                    walk(v, task_ctx)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, task_ctx)

        walk(data)
    except Exception:
        pass
    return calls


# ── Data Actions: Catálogo de ações da org ────────────────────────────────────
def fetch_data_actions_catalog():
    """Busca todas as Data Actions cadastradas na org (GET /api/v2/integrations/actions)."""
    global _data_actions_catalog_cache
    now = time.time()
    if _data_actions_catalog_cache["data"] and (now - _data_actions_catalog_cache["ts"]) < 600:
        return _data_actions_catalog_cache["data"]

    catalog = {}
    page = 1
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/api/v2/integrations/actions",
                headers=HEADERS,
                params={"pageSize": 200, "pageNumber": page},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"Erro ao buscar catálogo de Data Actions: HTTP {r.status_code}")
                break
            data = r.json()
            for e in data.get("entities", []):
                aid = e.get("id", "")
                integration = e.get("integration", {})
                catalog[aid] = {
                    "name":       e.get("name", ""),
                    "category":   e.get("category", ""),
                    "status":     e.get("status", ""),
                    "integration_name": integration.get("name", ""),
                    "integration_id":   integration.get("id", ""),
                }
            if page >= data.get("pageCount", 1):
                break
            page += 1
        except Exception as ex:
            print(f"Exceção ao buscar catálogo Data Actions: {ex}")
            break

    _data_actions_catalog_cache = {"data": catalog, "ts": now}
    return catalog


# ── Data Actions: Scanner de fluxo ────────────────────────────────────────────
def scan_flow_for_data_actions(cfg_uri):
    """Percorre o JSON do fluxo e retorna todas as Call Data Actions encontradas."""
    actions = []
    try:
        r = requests.get(f"{BASE_URL}{cfg_uri}", headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return actions
        data = r.json()

        def walk(obj, task_ctx=None):
            if isinstance(obj, dict):
                # Contexto da tarefa-pai (pasta no Architect)
                if obj.get("__type") == "Task" and "name" in obj:
                    task_ctx = obj.get("name") or task_ctx

                # Detecta CallDataAction (pode aparecer como vários __type)
                obj_type = obj.get("__type", "")
                is_data_action = obj_type in (
                    "CallDataAction", "DataAction", "dataAction",
                    "CallBridgeAction",
                )
                # Fallback: verifica se tem campo "dataAction" dentro do objeto
                if not is_data_action and "dataAction" in obj and isinstance(obj["dataAction"], dict):
                    is_data_action = True

                if is_data_action:
                    # Extrair referência à Data Action
                    da_ref = obj.get("dataAction", obj)
                    action_name = (
                        da_ref.get("name") or da_ref.get("actionName")
                        or obj.get("name") or obj.get("actionName") or "—"
                    )
                    action_id = (
                        da_ref.get("actionId") or da_ref.get("id")
                        or obj.get("actionId") or obj.get("id") or ""
                    )

                    # Extrair inputs
                    inputs_raw = obj.get("inputs", {})
                    inputs = []
                    if isinstance(inputs_raw, dict):
                        for k, v in inputs_raw.items():
                            if isinstance(v, dict):
                                val = v.get("text") or v.get("lit", {}).get("text") or str(v.get("config", ""))
                            else:
                                val = str(v)
                            inputs.append({"param": k, "value": val})
                    elif isinstance(inputs_raw, list):
                        for inp in inputs_raw:
                            name = inp.get("name", inp.get("key", ""))
                            val_obj = inp.get("value", {})
                            if isinstance(val_obj, dict):
                                val = val_obj.get("text") or str(val_obj.get("config", {}).get("lit", {}).get("text", ""))
                            else:
                                val = str(val_obj)
                            inputs.append({"param": name, "value": val})

                    # Extrair outputs
                    outputs_raw = obj.get("outputs", {})
                    outputs = []
                    if isinstance(outputs_raw, dict):
                        for k, v in outputs_raw.items():
                            if isinstance(v, dict):
                                val = v.get("name") or v.get("text") or str(v)
                            else:
                                val = str(v)
                            outputs.append({"param": k, "variable": val})
                    elif isinstance(outputs_raw, list):
                        for out in outputs_raw:
                            name = out.get("name", out.get("key", ""))
                            val = out.get("variable", out.get("value", ""))
                            if isinstance(val, dict):
                                val = val.get("name") or str(val)
                            outputs.append({"param": name, "variable": str(val)})

                    actions.append({
                        "action_id":   action_id,
                        "action_name": action_name,
                        "tracking_id": obj.get("trackingId", ""),
                        "parent_task": task_ctx or "—",
                        "inputs":      inputs,
                        "outputs":     outputs,
                    })

                for v in obj.values():
                    walk(v, task_ctx)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, task_ctx)

        walk(data)
        
        # O manifest sempre contém a lista oficial de dependências do fluxo com os actionIds corretos
        manifest_das = data.get("manifest", {}).get("dataAction", [])
        for mda in manifest_das:
            mid = mda.get("id", "")
            if mid and not any(a["action_id"] == mid for a in actions):
                actions.append({
                    "action_name": mda.get("name", "Unknown"),
                    "action_id":   mid,
                    "parent_task": "Manifest",
                    "inputs":      [],
                    "outputs":     []
                })
                
    except Exception as ex:
        print(f"Erro ao escanear fluxo para Data Actions: {ex}")
    return actions


# ── Data Actions: Health Check ────────────────────────────────────────────────
def run_health_check(action_ids):
    """Testa a conectividade de cada Data Action na lista de IDs."""
    results = []
    for aid in action_ids:
        start_t = time.time()
        try:
            r = requests.get(
                f"{BASE_URL}/api/v2/integrations/actions/{aid}",
                headers=HEADERS,
                timeout=10,
            )
            elapsed = int((time.time() - start_t) * 1000)
            if r.status_code == 200:
                data = r.json()
                status = data.get("status", "unknown")
                results.append({
                    "action_id": aid,
                    "name":      data.get("name", ""),
                    "status":    "ok" if status == "active" else "inactive",
                    "api_status": status,
                    "response_ms": elapsed,
                    "detail":    "",
                })
            else:
                results.append({
                    "action_id": aid, "name": "", "status": "error",
                    "api_status": f"HTTP {r.status_code}",
                    "response_ms": elapsed, "detail": r.text[:200],
                })
        except requests.exceptions.Timeout:
            results.append({
                "action_id": aid, "name": "", "status": "timeout",
                "api_status": "timeout", "response_ms": 10000, "detail": "Timeout 10s",
            })
        except Exception as ex:
            results.append({
                "action_id": aid, "name": "", "status": "error",
                "api_status": "exception", "response_ms": 0, "detail": str(ex)[:200],
            })
    return results


def _background_health_check():
    """Thread de background que executa health check periodicamente."""
    global _data_actions_health_cache
    while True:
        time.sleep(_health_check_interval)
        try:
            get_auth_token()
            # Pega os IDs do último scan
            scan_data = _data_actions_scan_cache.get("data") or []
            all_ids = []
            for flow in scan_data:
                for act in flow.get("data_actions", []):
                    aid = act.get("action_id", "")
                    if aid and aid not in all_ids:
                        all_ids.append(aid)
            if all_ids:
                results = run_health_check(all_ids)
                _data_actions_health_cache = {
                    "results": results,
                    "ts": time.time(),
                }
                ok = sum(1 for r in results if r["status"] == "ok")
                print(f"[HealthCheck] {ok}/{len(results)} Data Actions online.")
        except Exception as ex:
            print(f"[HealthCheck] Erro: {ex}")


# ── Processa conversa → CDR ────────────────────────────────────────────────────
def process_conversation(conv, flow_id_filter):
    cid  = conv.get("conversationId", "—")
    start = fmt_dt(conv.get("conversationStart"))
    end   = fmt_dt(conv.get("conversationEnd"))

    # Duração total
    try:
        cs = datetime.fromisoformat(conv.get("conversationStart","").replace("Z","+00:00"))
        ce = datetime.fromisoformat(conv.get("conversationEnd","").replace("Z","+00:00"))
        duration_ms = int((ce - cs).total_seconds() * 1000)
    except:
        duration_ms = None

    direction = DIR_MAP.get(conv.get("originatingDirection","").lower(), conv.get("originatingDirection","—"))

    # Coleta dados dos participantes/sessões
    ani = dnis = queue = agent = flow_name = flow_type = segment_type = disc_type = "—"
    talk_ms = hold_ms = wait_ms = 0

    for part in conv.get("participants", []):
        purpose = part.get("purpose", "")
        for sess in part.get("sessions", []):
            # ANI / DNIS
            if sess.get("ani") and ani == "—":
                ani = sess["ani"]
            if sess.get("dnis") and dnis == "—":
                dnis = sess["dnis"]

            # Dados de fluxo — sess.flowData[] (voice) ou sess.flow{} (digital)
            for fd in sess.get("flowData", []):
                if not flow_id_filter or fd.get("flowId") == flow_id_filter:
                    if flow_name == "—":
                        flow_name = fd.get("flowName", "—")
                    if flow_type == "—":
                        raw_ft = fd.get("flowType", "")
                        flow_type = FLOW_TYPE_MAP.get(raw_ft, raw_ft) or "—"

            # Objeto flow direto na sessão (Digital/Bot flows)
            sess_flow = sess.get("flow", {})
            if sess_flow and (not flow_id_filter or sess_flow.get("flowId") == flow_id_filter):
                if flow_name == "—":
                    flow_name = sess_flow.get("flowName", "—")
                if flow_type == "—":
                    raw_ft = sess_flow.get("flowType", "")
                    flow_type = FLOW_TYPE_MAP.get(raw_ft, raw_ft) or "—"

        # FlowData no nível do participante (fallback)
        for fd in part.get("flowData", []):
            if not flow_id_filter or fd.get("flowId") == flow_id_filter:
                if flow_name == "—":
                    flow_name = fd.get("flowName", "—")
                if flow_type == "—":
                    raw_ft = fd.get("flowType", "")
                    flow_type = FLOW_TYPE_MAP.get(raw_ft, raw_ft) or "—"

            # Queue
            if purpose == "acd" and sess.get("queueId") and queue == "—":
                queue = sess.get("queueName", sess.get("queueId", "—"))

            # Agente
            if purpose == "agent" and agent == "—":
                agent = part.get("participantName", part.get("userId", "—"))

            # Segmentos: tempos e tipo
            for seg in sess.get("segments", []):
                st = seg.get("segmentType", "")
                ms = seg.get("durationMs", 0) or 0
                if st == "interact":
                    talk_ms += ms
                elif st == "hold":
                    hold_ms += ms
                elif st in ("acd", "ivr"):
                    wait_ms += ms
                if segment_type == "—" and st:
                    segment_type = SEG_MAP.get(st, st)
                if disc_type == "—":
                    dt_ = seg.get("disconnectType", "")
                    if dt_:
                        disc_type = DISC_MAP.get(dt_.lower(), dt_)

    return {
        "conversation_id": cid,
        "start":           start,
        "end":             end,
        "duration":        fmt_duration(duration_ms),
        "direction":       direction,
        "ani":             ani,
        "dnis":            dnis,
        "queue":           queue,
        "agent":           agent,
        "flow_name":       flow_name,
        "flow_type":       flow_type,
        "segment_type":    segment_type,
        "disconnect_type": disc_type,
        "talk_time":       fmt_duration(talk_ms) if talk_ms else "—",
        "hold_time":       fmt_duration(hold_ms) if hold_ms else "—",
        "wait_time":       fmt_duration(wait_ms) if wait_ms else "—",
    }


# ── Rotas Flask ───────────────────────────────────────────────────────────────
@app.route("/")
def index():
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("index.html", today=today)


@app.route("/api/flows")
def api_flows():
    allowed, hits, req_c = check_rate()
    if not allowed:
        return jsonify({"error": f"Rate limit local: {RATE_LIMIT_RPM} req/min.", "flows": []}), 429
    
    get_auth_token() # Garante token válido
    flows = fetch_flows()
    return jsonify({"flows": flows})


@app.route("/api/cdr-tasks")
def api_cdr_tasks():
    """Escaneia fluxos e retorna Call Task CDR. Se flowId=x, escaneia só esse fluxo."""
    global _cdr_tasks_cache
    now = time.time()
    flow_id_filter = request.args.get("flowId", "")

    get_auth_token() # Garante token válido

    # Scan de fluxo único — rápido, sem cache global
    if flow_id_filter:
        r = requests.get(f"{BASE_URL}/api/v2/flows/{flow_id_filter}", headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return jsonify({"flows": [], "error": f"Fluxo não encontrado ({r.status_code})"}), 200
        e = r.json()
        pub = e.get("publishedVersion") or e.get("checkedInVersion") or {}
        cfg_uri = pub.get("configurationUri", "")
        calls = scan_flow_for_cdr_tasks(cfg_uri) if cfg_uri else []
        if calls:
            update_daily_snapshot(flow_id_filter, calls)
        diffs = get_flow_history_diffs(flow_id_filter, calls)
        
        result = [{
            "flow_id":   e.get("id", ""),
            "flow_name": e.get("name", ""),
            "flow_type": FLOW_TYPE_MAP.get(e.get("type", ""), e.get("type", "")),
            "count":     len(calls),
            "cdr_calls": calls,
            "history":   diffs,
        }] if calls else []
        return jsonify({"flows": result, "cached": False})

    # Scan completo — usa cache de 10 min
    if _cdr_tasks_cache["data"] is not None and (now - _cdr_tasks_cache["ts"]) < 600:
        return jsonify({"flows": _cdr_tasks_cache["data"], "cached": True,
                        "cached_age_s": int(now - _cdr_tasks_cache["ts"])})

    results = []
    page = 1
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/api/v2/flows",
                headers=HEADERS,
                params={"pageSize": 100, "pageNumber": page, "deleted": "false"},
                timeout=15,
            )
            if r.status_code != 200:
                break
            data = r.json()
            for e in data.get("entities", []):
                pub = e.get("publishedVersion") or e.get("checkedInVersion") or {}
                cfg_uri = pub.get("configurationUri", "")
                if not cfg_uri:
                    continue
                calls = scan_flow_for_cdr_tasks(cfg_uri)
                if calls:
                    update_daily_snapshot(e.get("id", ""), calls)
                    diffs = get_flow_history_diffs(e.get("id", ""), calls)
                    results.append({
                        "flow_id":   e.get("id", ""),
                        "flow_name": e.get("name", ""),
                        "flow_type": FLOW_TYPE_MAP.get(e.get("type", ""), e.get("type", "")),
                        "count":     len(calls),
                        "cdr_calls": calls,
                        "history":   diffs,
                    })
            if page >= data.get("pageCount", 1):
                break
            page += 1
        except Exception as e:
            print(f"Erro durante o scan de Call Tasks: {e}")
            break

    _cdr_tasks_cache = {"data": results, "ts": now}
    return jsonify({"flows": results, "cached": False})




@app.route("/api/cdr")
def api_cdr():
    global rate_hits
    allowed, hits, req_c = check_rate()
    if not allowed:
        return jsonify({
            "error": f"Rate limit local ({RATE_LIMIT_RPM} req/min). Aguarde.",
            "rate_limit_hit": True, "rate_limit_hits": hits,
            "alert": hits % 10 == 0,
            "records": [], "stats": {}, "pagination": {}
        }), 429

    start_date    = request.args.get("startDate", datetime.now().strftime("%Y-%m-%d"))
    end_date      = request.args.get("endDate",   datetime.now().strftime("%Y-%m-%d"))
    flow_id       = request.args.get("flowId",    "")
    direction_f   = request.args.get("direction", "")
    page          = int(request.args.get("page", 1))

    # Monta intervalo ISO 8601
    interval = f"{start_date}T00:00:00.000Z/{end_date}T23:59:59.999Z"

    base_body = {
        "interval": interval,
        "order":    "asc",
        "orderBy":  "conversationStart",
        "paging":   {"pageSize": 100, "pageNumber": 1},
        "segmentFilters": [],
        "conversationFilters": [],
        "evaluationFilters":   [],
        "surveyFilters":       [],
    }

    # Filtro por flowId
    if flow_id:
        base_body["segmentFilters"].append({
            "type": "and",
            "predicates": [{"dimension": "flowId", "value": flow_id}]
        })

    # Filtro por direção
    if direction_f:
        base_body["conversationFilters"].append({
            "type": "and",
            "predicates": [{"dimension": "originatingDirection", "value": direction_f}]
        })

    get_auth_token()  # Garante token válido

    # Pagina pela API da Genesys (máx 1000 registros = 10 páginas × 100)
    convs = []
    genesys_page = 1
    MAX_GENESYS_PAGES = 10
    try:
        while genesys_page <= MAX_GENESYS_PAGES:
            body = dict(base_body)
            body["paging"] = {"pageSize": 100, "pageNumber": genesys_page}
            resp = requests.post(
                f"{BASE_URL}/api/v2/analytics/conversations/details/query",
                headers=HEADERS,
                json=body,
                timeout=20,
            )

            if resp.status_code == 429:
                rate_hits += 1
                return jsonify({
                    "error": "Rate limit da Genesys (429). Aguarde antes de tentar novamente.",
                    "rate_limit_hit": True, "rate_limit_hits": rate_hits,
                    "alert": rate_hits % 10 == 0,
                    "records": [], "stats": {}, "pagination": {}
                }), 200

            if resp.status_code != 200:
                if not convs:  # Falhou já na 1ª página: retorna erro
                    return jsonify({
                        "error": genesys_error(resp),
                        "records": [], "stats": {}, "pagination": {}
                    }), 200
                break  # Falha em página intermediária: usa o que já buscou

            data = resp.json()
            page_convs = data.get("conversations", [])
            convs.extend(page_convs)

            total_hits = data.get("totalHits", 0)
            if not page_convs or len(convs) >= total_hits:
                break
            genesys_page += 1

    except requests.exceptions.Timeout:
        if not convs:
            return jsonify({"error": "Timeout: Genesys não respondeu em 20s.", "records": [], "stats": {}, "pagination": {}}), 200
    except requests.exceptions.ConnectionError:
        if not convs:
            return jsonify({"error": "Falha de conexão. Verifique sua internet.", "records": [], "stats": {}, "pagination": {}}), 200
    except Exception as e:
        if not convs:
            return jsonify({"error": f"Erro inesperado: {str(e)}", "records": [], "stats": {}, "pagination": {}}), 200

    # Processar
    all_records = [process_conversation(c, flow_id) for c in convs]

    # Stats
    total     = len(all_records)
    receptivo = sum(1 for r in all_records if r["direction"] == "Receptivo")
    ativo     = sum(1 for r in all_records if r["direction"] == "Ativo")
    c_agent   = sum(1 for r in all_records if r["agent"] != "—")
    c_bot     = sum(1 for r in all_records if r["agent"] == "—")

    stats = {
        "total":     total,
        "receptivo": receptivo,
        "ativo":     ativo,
        "com_agente": c_agent,
        "apenas_bot": c_bot,
    }

    # Paginação local
    total_pages = max(1, -(-total // PAGE_SIZE))
    page        = max(1, min(page, total_pages))
    s_idx       = (page - 1) * PAGE_SIZE
    page_recs   = all_records[s_idx:s_idx + PAGE_SIZE]

    return jsonify({
        "records":    page_recs,
        "stats":      stats,
        "pagination": {
            "page": page, "page_size": PAGE_SIZE,
            "total": total, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages,
        },
        "rate_limit_hits":      hits,
        "requests_last_minute": req_c,
        "alert": False,
    })


@app.route("/api/cdr/export")
def api_cdr_export():
    """Exporta todos os CDRs filtrados como arquivo CSV."""
    import csv, io

    start_date  = request.args.get("startDate", datetime.now().strftime("%Y-%m-%d"))
    end_date    = request.args.get("endDate",   datetime.now().strftime("%Y-%m-%d"))
    flow_id     = request.args.get("flowId",    "")
    direction_f = request.args.get("direction", "")

    interval = f"{start_date}T00:00:00.000Z/{end_date}T23:59:59.999Z"

    base_body = {
        "interval": interval,
        "order":    "asc",
        "orderBy":  "conversationStart",
        "paging":   {"pageSize": 100, "pageNumber": 1},
        "segmentFilters":      [],
        "conversationFilters": [],
        "evaluationFilters":   [],
        "surveyFilters":       [],
    }
    if flow_id:
        base_body["segmentFilters"].append({
            "type": "and",
            "predicates": [{"dimension": "flowId", "value": flow_id}]
        })
    if direction_f:
        base_body["conversationFilters"].append({
            "type": "and",
            "predicates": [{"dimension": "originatingDirection", "value": direction_f}]
        })

    get_auth_token()

    convs = []
    genesys_page = 1
    MAX_EXPORT_PAGES = 50  # até 5000 registros
    try:
        while genesys_page <= MAX_EXPORT_PAGES:
            body = dict(base_body)
            body["paging"] = {"pageSize": 100, "pageNumber": genesys_page}
            resp = requests.post(
                f"{BASE_URL}/api/v2/analytics/conversations/details/query",
                headers=HEADERS, json=body, timeout=25,
            )
            if resp.status_code != 200:
                if not convs:
                    return jsonify({"error": genesys_error(resp)}), 200
                break
            data = resp.json()
            page_convs = data.get("conversations", [])
            convs.extend(page_convs)
            total_hits = data.get("totalHits", 0)
            if not page_convs or len(convs) >= total_hits:
                break
            genesys_page += 1
    except Exception as e:
        if not convs:
            return jsonify({"error": f"Erro ao buscar dados: {str(e)}"}), 200

    records = [process_conversation(c, flow_id) for c in convs]

    # Gera CSV em memória
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writerow([
        "ID Conversa", "Início", "Fim", "Duração",
        "Direção", "ANI (Origem)", "DNIS (Destino)",
        "Fluxo", "Tipo Fluxo", "Fila", "Agente",
        "Tempo Atendimento", "Tempo Espera", "Desconexão"
    ])
    for r in records:
        writer.writerow([
            r.get("conversation_id", ""),
            r.get("start", ""),
            r.get("end", ""),
            r.get("duration", ""),
            r.get("direction", ""),
            r.get("ani", ""),
            r.get("dnis", ""),
            r.get("flow_name", ""),
            r.get("flow_type", ""),
            r.get("queue", ""),
            r.get("agent", ""),
            r.get("talk_time", ""),
            r.get("hold_time", ""),
            r.get("disconnect_type", ""),
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM para Excel abrir corretamente
    filename  = f"CDR_{start_date}_{end_date}.csv"

    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.route("/api/rate-status")
def rate_status():
    now = time.time()
    while request_times and request_times[0] < now - 60:
        request_times.popleft()
    return jsonify({
        "requests_last_minute": len(request_times),
        "limit": RATE_LIMIT_RPM,
        "rate_limit_hits": rate_hits,
    })




# ── Data Actions: Rotas ───────────────────────────────────────────────────────

@app.route("/api/flow-data-actions")
def api_flow_data_actions():
    """Escaneia um fluxo e retorna todas as Call Data Actions."""
    flow_id = request.args.get("flowId", "")
    if not flow_id:
        return jsonify({"error": "Parâmetro flowId é obrigatório.", "flows": []}), 400

    get_auth_token()

    # Verificação rápida: testa se a API de Data Actions responde
    try:
        test_r = requests.get(
            f"{BASE_URL}/api/v2/integrations/actions",
            headers=HEADERS,
            params={"pageSize": 1},
            timeout=10,
        )
        if test_r.status_code != 200:
            return jsonify({
                "error": f"API de Data Actions inacessível (HTTP {test_r.status_code}). Verifique as permissões do token.",
                "flows": [], "api_check": False,
            }), 200
    except Exception as ex:
        return jsonify({
            "error": f"Falha ao conectar na API de Data Actions: {str(ex)}",
            "flows": [], "api_check": False,
        }), 200

    # Buscar o fluxo
    try:
        r = requests.get(f"{BASE_URL}/api/v2/flows/{flow_id}", headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return jsonify({"error": f"Fluxo não encontrado ({r.status_code})", "flows": []}), 200
        flow_data = r.json()
    except Exception as ex:
        return jsonify({"error": f"Erro ao buscar fluxo: {str(ex)}", "flows": []}), 200

    pub = flow_data.get("publishedVersion") or flow_data.get("checkedInVersion") or {}
    cfg_uri = pub.get("configurationUri", "")
    if not cfg_uri:
        return jsonify({"error": "Fluxo sem configurationUri publicada.", "flows": []}), 200

    # Escanear o fluxo
    actions = scan_flow_for_data_actions(cfg_uri)

    # Enriquecer com o catálogo
    catalog = fetch_data_actions_catalog()
    for act in actions:
        cat_entry = catalog.get(act["action_id"], {})
        act["integration_name"] = cat_entry.get("integration_name", "")
        act["category"]         = cat_entry.get("category", "")
        act["catalog_status"]   = cat_entry.get("status", "")

    result = [{
        "flow_id":   flow_data.get("id", ""),
        "flow_name": flow_data.get("name", ""),
        "flow_type": FLOW_TYPE_MAP.get(flow_data.get("type", ""), flow_data.get("type", "")),
        "count":     len(actions),
        "data_actions": actions,
    }]

    # Salvar no cache para health check
    global _data_actions_scan_cache
    _data_actions_scan_cache = {"data": result, "ts": time.time(), "flow_id": flow_id}

    return jsonify({"flows": result, "api_check": True, "catalog_size": len(catalog)})


@app.route("/api/data-action-test", methods=["POST"])
def api_data_action_test():
    """Testa uma Data Action individual."""
    body = request.get_json(silent=True) or {}
    action_id = body.get("actionId", "")
    if not action_id:
        return jsonify({"error": "actionId é obrigatório."}), 400

    get_auth_token()

    start_t = time.time()
    try:
        r = requests.get(
            f"{BASE_URL}/api/v2/integrations/actions/{action_id}",
            headers=HEADERS,
            timeout=10,
        )
        elapsed = int((time.time() - start_t) * 1000)

        if r.status_code == 200:
            data = r.json()
            api_status = data.get("status", "unknown")
            return jsonify({
                "status":      "ok" if api_status == "active" else "inactive",
                "api_status":  api_status,
                "name":        data.get("name", ""),
                "integration": data.get("integration", {}).get("name", ""),
                "response_ms": elapsed,
                "detail":      "",
            })
        else:
            return jsonify({
                "status": "error", "api_status": f"HTTP {r.status_code}",
                "response_ms": elapsed, "detail": r.text[:300],
            })
    except requests.exceptions.Timeout:
        return jsonify({
            "status": "timeout", "api_status": "timeout",
            "response_ms": 10000, "detail": "Timeout de 10 segundos excedido.",
        })
    except Exception as ex:
        return jsonify({
            "status": "error", "api_status": "exception",
            "response_ms": 0, "detail": str(ex)[:300],
        })


@app.route("/api/data-actions-health")
def api_data_actions_health():
    """Retorna o último resultado do health check e permite forçar um novo."""
    force = request.args.get("force", "false").lower() == "true"

    get_auth_token()

    if force:
        scan_data = _data_actions_scan_cache.get("data") or []
        all_ids = []
        for flow in scan_data:
            for act in flow.get("data_actions", []):
                aid = act.get("action_id", "")
                if aid and aid not in all_ids:
                    all_ids.append(aid)
        if not all_ids:
            return jsonify({"error": "Nenhuma Data Action escaneada ainda. Execute um scan primeiro.", "results": []})

        results = run_health_check(all_ids)
        global _data_actions_health_cache
        _data_actions_health_cache = {"results": results, "ts": time.time()}
    else:
        results = _data_actions_health_cache.get("results") or []

    ok_count = sum(1 for r in results if r["status"] == "ok")
    return jsonify({
        "results":       results,
        "total":         len(results),
        "online":        ok_count,
        "last_check_ts": _data_actions_health_cache.get("ts", 0),
        "interval_s":    _health_check_interval,
    })


@app.route("/api/data-actions-health/interval", methods=["POST"])
def api_set_health_interval():
    """Altera o intervalo do health check automático."""
    global _health_check_interval
    body = request.get_json(silent=True) or {}
    seconds = body.get("seconds", 3 * 3600)
    if seconds < 1800:  # mínimo 30 min
        seconds = 1800
    _health_check_interval = seconds
    hours = seconds / 3600
    return jsonify({"interval_s": seconds, "interval_h": round(hours, 1)})



# ── Data Actions: Performance Analytics ──────────────────────────────────────

@app.route("/api/data-actions-performance", methods=["POST"])
def api_data_actions_performance():
    """
    Retorna métricas de desempenho de todas as Data Actions na Org (Global).
    Usa POST /api/v2/analytics/actions/aggregates/query da Genesys Cloud.
    """
    body = request.get_json(silent=True) or {}
    hours       = body.get("hours")
    start_date  = body.get("startDate", "")
    end_date    = body.get("endDate", "")
    granularity = body.get("granularity", "PT1H")

    get_auth_token()

    # ── Montar intervalo ISO 8601 ────────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    if hours:
        start_utc = now_utc - timedelta(hours=int(hours))
        interval_str = (
            f"{start_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')}/"
            f"{now_utc.strftime('%Y-%m-%dT%H:%M:%S.999Z')}"
        )
        if int(hours) <= 2:
            granularity = "PT15M"
    else:
        if not start_date:
            start_date = now_utc.strftime("%Y-%m-%d")
        if not end_date:
            end_date   = now_utc.strftime("%Y-%m-%d")
        interval_str = f"{start_date}T00:00:00.000Z/{end_date}T23:59:59.999Z"

    # ── Query 1: Breakdown por responseStatus ──────────────────────────────────
    query_body_1 = {
        "interval":    interval_str,
        "granularity": granularity,
        "groupBy":     ["actionId", "actionName", "actionCategory", "responseStatus"],
        "metrics":     ["tTotalExecution"],
        "flattenMultivaluedDimensions": True,
    }

    by_action = {}

    try:
        resp1 = requests.post(f"{BASE_URL}/api/v2/analytics/actions/aggregates/query", headers=HEADERS, json=query_body_1, timeout=30)
        if resp1.status_code == 200:
            for grp in resp1.json().get("results", []):
                g      = grp.get("group", {})
                aid    = g.get("actionId", "")
                aname  = g.get("actionName", "")
                acat   = g.get("actionCategory", "")
                status = g.get("responseStatus", "?")

                if aid not in by_action:
                    aid_clean = aid.split("_-_")[-1] if "_-_" in aid else aid
                    by_action[aid] = {
                        "action_id":    aid,
                        "action_id_clean": aid_clean,
                        "action_name":  aname or aid,
                        "category":     acat or "Desconhecida",
                        "nExecutions":  0,
                        "nExecutionsSuccess": 0,
                        "nExecutionsFailure": 0,
                        "tExecutionTime": 0,
                        "p95_ms": 0,
                        "p99_ms": 0,
                        "by_status": {},
                        "by_error_type": {},
                    }
                rec = by_action[aid]

                for datum in grp.get("data", []):
                    mm    = {m["metric"]: m for m in datum.get("metrics", [])}
                    stats = (mm.get("tTotalExecution") or {}).get("stats", {})
                    cnt   = stats.get("count", 0) or 0
                    tsum  = stats.get("sum", 0) or 0
                    p95   = stats.get("p95", 0) or 0
                    p99   = stats.get("p99", 0) or 0
                    interval_lbl = datum.get("interval", "unknown")

                    rec["nExecutions"]    += cnt
                    rec["tExecutionTime"] += tsum
                    if p95 > rec["p95_ms"]: rec["p95_ms"] = p95
                    if p99 > rec["p99_ms"]: rec["p99_ms"] = p99
                    rec["by_status"][status] = rec["by_status"].get(status, 0) + cnt
                    
                    if status.startswith("2"):
                        rec["nExecutionsSuccess"] += cnt
                    else:
                        rec["nExecutionsFailure"] += cnt
                        
                    s_map = rec.setdefault("_series_map", {})
                    s = s_map.setdefault(interval_lbl, {"interval": interval_lbl, "nExecutions": 0, "nExecutionsFailure": 0, "tExecutionTime": 0})
                    s["nExecutions"] += cnt
                    s["tExecutionTime"] += tsum
                    if not status.startswith("2"):
                        s["nExecutionsFailure"] += cnt

    except Exception as ex:
        return jsonify({"error": f"Erro na Query 1 (Status): {str(ex)}"}), 200

    # ── Query 2: Breakdown por errorType ───────────────────────────────────────
    query_body_2 = {
        "interval":    interval_str,
        "granularity": granularity,
        "groupBy":     ["actionId", "errorType"],
        "metrics":     ["tTotalExecution"],
        "flattenMultivaluedDimensions": True,
    }

    try:
        resp2 = requests.post(f"{BASE_URL}/api/v2/analytics/actions/aggregates/query", headers=HEADERS, json=query_body_2, timeout=30)
        if resp2.status_code == 200:
            for grp in resp2.json().get("results", []):
                g     = grp.get("group", {})
                aid   = g.get("actionId", "")
                etype = g.get("errorType", "?")
                
                if aid not in by_action:
                    continue
                
                cnt = sum(
                    ((mm.get("tTotalExecution") or {}).get("stats", {}).get("count") or 0)
                    for datum in grp.get("data", [])
                    for mm in [{m["metric"]: m for m in datum.get("metrics", [])}]
                )
                if cnt > 0:
                    by_action[aid]["by_error_type"][etype] = by_action[aid]["by_error_type"].get(etype, 0) + cnt
    except Exception as ex:
        pass # Ignora falhas na query 2, pois a query 1 é mais importante

    # ── Finaliza e agrupa as métricas ─────────────────────────────────────────
    result_actions = []
    tot_e = tot_s = tot_f = tot_t = 0

    for aid, perf in by_action.items():
        n_exec    = perf["nExecutions"]
        n_success = perf["nExecutionsSuccess"]
        n_failure = perf["nExecutionsFailure"]
        t_exec    = perf["tExecutionTime"]

        tot_e += n_exec
        tot_s += n_success
        tot_f += n_failure
        tot_t += t_exec

        success_rate = round((n_success / n_exec * 100), 1) if n_exec > 0 else None
        avg_latency  = round(t_exec / n_exec)             if n_exec > 0 else None

        if success_rate is None:
            status = "no_data"
        elif success_rate >= 95:
            status = "ok"
        elif success_rate >= 80:
            status = "warn"
        else:
            status = "critical"

        series_list = sorted(perf.pop("_series_map", {}).values(), key=lambda x: x["interval"])
        result_actions.append({
            **perf,
            "success_rate":  success_rate,
            "avg_latency_ms": avg_latency,
            "status":        status,
            "series":        series_list,
        })

    # Ordenar por total de execuções (desc)
    result_actions.sort(key=lambda x: x["nExecutions"], reverse=True)

    # ── Resumo geral ───────────────────────────────────────────────────────────
    summary = {
        "total_executions":  tot_e,
        "total_success":     tot_s,
        "total_failure":     tot_f,
        "success_rate":      round(tot_s / tot_e * 100, 1) if tot_e > 0 else None,
        "error_rate":        round(tot_f / tot_e * 100, 1) if tot_e > 0 else None,
        "avg_latency_ms":    round(tot_t / tot_e)          if tot_e > 0 else None,
        "actions_analyzed":  len(result_actions),
        "actions_no_data":   0,
    }

    return jsonify({
        "flow_name":    "Visão Global de Data Actions",
        "interval":     interval_str,
        "granularity":  "PT24H",
        "actions":      result_actions,
        "summary":      summary,
    })


if __name__ == "__main__":
    # Inicia thread de health check em background
    _health_check_thread = threading.Thread(target=_background_health_check, daemon=True)
    _health_check_thread.start()
    app.run(debug=True, port=5051)
