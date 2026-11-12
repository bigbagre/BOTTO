from datetime import datetime, timedelta

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from google.genai import types
from google import genai
import base64
import io
import json
import queue
import re
import threading
import numpy as np
import sounddevice as sd
import vosk
import pygame
import openwakeword
from openwakeword.model import Model as WakeWordModel
import pyaudio
from dotenv import load_dotenv
import soundfile as sf
import espeakng_loader
from kokoro import KPipeline
import os
import sys
import hashlib
import sqlite3
import time

from argon2 import PasswordHasher
import secrets

hasher = PasswordHasher()

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, '..', '..', 'database.db')

def get_db():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def execute_sql(conn, sql, params=()):
    cursor = conn.cursor()
    cursor.execute(sql, params)
    conn.commit()
    return cursor

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

# =========================
# CONFIGURAÇÃO FLASK
# =========================
app = Flask(__name__)
CORS(app)


# =========================
# CONFIGURAÇÃO API
# =========================
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

gemini_key = os.environ.get("GEMINI_API_KEY")

if not gemini_key:
    raise EnvironmentError("Variável de ambiente faltando: GEMINI_API_KEY. Verifique o arquivo .env em APP\\electron\\")

try:
    client = genai.Client(api_key=gemini_key)
except Exception as e:
    raise EnvironmentError(f"Erro ao inicializar cliente Gemini: {str(e)}")

model_name = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# =========================
# CONFIGURAÇÃO KOKORO TTS
# =========================
tts_pipeline = KPipeline(lang_code='p')  # 'p' = português brasileiro
KOKORO_VOICE = 'pm_alex'                 # ou 'pf_dora', 'pm_santa'
tts_lock = threading.Lock()              # Flask e o loop de voz podem chamar ao mesmo tempo

system_instruction = (
    'Você é o Botto, assistente técnico. '
    'Seja objetivo. '
    'Não dê respostas prontas - encoraje o usuário a pesquisar.'
    'Em dúvidas acadêmicas, indique o caminho, não a resposta.'
    'Responda em português brasileiro.'
)

# =========================
# CONFIGURAÇÃO ELEVENLABS
# =========================
el_client = None
VOICE_ID = KOKORO_VOICE

# =========================
# CONFIGURAÇÃO VOSK
# =========================
vosk.SetLogLevel(-1)
vosk_model = vosk.Model(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model-small-pt-0.3"))
rec = vosk.KaldiRecognizer(vosk_model, 16000)
vosk_queue = queue.Queue()

def vosk_callback(indata, frames, time, status):
    vosk_queue.put(bytes(indata))

# =========================
# CONFIGURAÇÃO PYGAME
# =========================
pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)

# =========================
# CONFIGURAÇÃO OPENWAKEWORD
# =========================
openwakeword.utils.download_models()
wakeword_model = WakeWordModel(
    wakeword_models=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "Hey_Jarvis.onnx")],
    inference_framework="onnx"
)

pa = pyaudio.PyAudio()
audio_stream = pa.open(
    rate=16000,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    frames_per_buffer=1280,
    input_device_index=1
)

# =========================
# ESTADO GLOBAL
# =========================
modo_atual = "texto"
sse_clients = []
voz_thread = None
voz_ativa = False

# =========================
# SSE: ENVIAR EVENTOS
# =========================
def push_evento(tipo, dados):
    payload = json.dumps({"tipo": tipo, "dados": dados})
    for q in sse_clients:
        q.put(payload)

# =========================
# FUNÇÕES AUXILIARES
# =========================
def gerar_audio(texto, voz_idx=None, speed=0.9, pausa=0.35):
    """Gera áudio com o Kokoro oficial e devolve WAV em base64."""
    try:
        texto_tts = traduzir_latex_para_voz(texto)
        texto_tts = re.sub(r'[*#`_]', '', texto_tts)
        frases = [f.strip() for f in re.split(r'(?<=[.!?])\s+|\n+', texto_tts) if f.strip()]
        if not frases:
            return None

        sr = 24000
        silencio = np.zeros(int(sr * pausa), dtype=np.float32)
        pedacos = []

        with tts_lock:
            for frase in frases:
                for _, _, audio in tts_pipeline(frase, voice=KOKORO_VOICE, speed=speed):
                    a = audio.detach().cpu().numpy() if hasattr(audio, 'detach') else np.asarray(audio)
                    pedacos.append(a.astype(np.float32))
                pedacos.append(silencio)

        wav = np.concatenate(pedacos[:-1])
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        push_evento("log", {"tag": "ERR", "msg": f"Erro TTS: {str(e)}"})
        return None

def reproduzir_audio_b64(audio_b64):
    """Reproduz áudio base64 via pygame — usado no modo voz."""
    if not audio_b64:
        return
    try:
        audio_bytes = base64.b64decode(audio_b64)
        pygame.mixer.music.load(io.BytesIO(audio_bytes))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    except Exception as e:
        push_evento("log", {"tag": "ERR", "msg": f"Erro reproduzir áudio: {str(e)}"})

def e_fim_de_frase(texto):
    """Verifica se o texto acumulado tem uma frase completa para mandar ao TTS."""
    import re
    return bool(re.search(r'[.!?;,\n]', texto)) and len(texto) > 20

def gerar_e_enviar_chunk(trecho, indice):
    """Gera o áudio de um trecho (WAV em base64) e envia via SSE para o app tocar."""
    audio_b64 = gerar_audio(trecho.strip())
    if audio_b64:
        push_evento("stream_audio_chunk", {"audio": audio_b64, "indice": indice})

def processar_latex(texto):
    import re
    texto = re.sub(r'\$\$(.+?)\$\$', r'<div class="math-block">$1</div>', texto, flags=re.DOTALL)
    texto = re.sub(r'\\\[(.+?)\\\]', r'<div class="math-block">$1</div>', texto, flags=re.DOTALL)
    texto = re.sub(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', r'<span class="math-inline">$1</span>', texto)
    return texto

# =========================
# LATEX -> FALA (TTS)
# =========================
_SIMBOLOS = {
    'alpha': 'alfa', 'beta': 'beta', 'gamma': 'gama', 'delta': 'delta',
    'Delta': 'delta', 'epsilon': 'épsilon', 'theta': 'teta', 'lambda': 'lâmbda',
    'mu': 'mi', 'pi': 'pi', 'sigma': 'sigma', 'omega': 'ômega', 'rho': 'rô',
    'phi': 'fi', 'tau': 'tau',
    'times': 'vezes', 'cdot': 'vezes', 'div': 'dividido por',
    'pm': 'mais ou menos',
    'leq': 'menor ou igual a', 'le': 'menor ou igual a',
    'geq': 'maior ou igual a', 'ge': 'maior ou igual a', 'neq': 'diferente de',
    'approx': 'aproximadamente', 'to': 'tende a', 'rightarrow': 'leva a',
    'infty': 'infinito', 'partial': 'd parcial', 'in': 'pertence a',
    'sin': 'seno', 'cos': 'cosseno', 'tan': 'tangente',
    'ln': 'logaritmo natural de', 'log': 'logaritmo de', 'exp': 'exponencial de',
    'dots': 'reticências', 'ldots': 'reticências',
}

_OPERADORES = {
    '+': 'mais', '-': 'menos', '=': 'igual a', '<': 'menor que',
    '>': 'maior que', '*': 'vezes', '/': 'dividido por', '%': 'por cento',
}

_TEXTO_PURO = ('text', 'mathrm', 'mathbf', 'mathit', 'mathbb', 'operatorname')

_PADRAO_LATEX = re.compile(
    r'\$\$(.+?)\$\$'                          # $$ ... $$
    r'|\\\[(.+?)\\\]'                         # \[ ... \]
    r'|\\\((.+?)\\\)'                         # \( ... \)
    r'|(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)',  # $ ... $
    re.DOTALL
)


def _ler_arg(s, i):
    """Lê um argumento LaTeX a partir de s[i]: {...}, \\comando ou um caractere."""
    while i < len(s) and s[i] == ' ':
        i += 1
    if i >= len(s):
        return '', i
    if s[i] == '{':
        nivel = 0
        for j in range(i, len(s)):
            if s[j] == '{':
                nivel += 1
            elif s[j] == '}':
                nivel -= 1
                if nivel == 0:
                    return s[i + 1:j], j + 1
        return s[i + 1:], len(s)
    if s[i] == '\\':
        m = re.match(r'\\[a-zA-Z]+', s[i:])
        if m:
            return m.group(0), i + m.end()
        return s[i:i + 2], i + 2
    return s[i], i + 1


def _ler_limites(s, i):
    """Lê os limites _{baixo}^{cima} de \\int, \\sum, \\prod e \\lim."""
    baixo = cima = None
    for _ in range(2):
        j = i
        while j < len(s) and s[j] == ' ':
            j += 1
        if j < len(s) and s[j] == '_' and baixo is None:
            baixo, i = _ler_arg(s, j + 1)
        elif j < len(s) and s[j] == '^' and cima is None:
            cima, i = _ler_arg(s, j + 1)
        else:
            break
    return baixo, cima, i


def _latex_expr_para_fala(s):
    s = re.sub(r'\\(left|right|displaystyle|bigg?|Bigg?)(?![a-zA-Z])', '', s)
    s = re.sub(r'\\[,;:! ]', ' ', s)
    s = re.sub(r'\^\s*\\circ\.?', ' graus ', s)
    out = []
    i = 0
    while i < len(s):
        c = s[i]

        if c == '\\':
            m = re.match(r'\\([a-zA-Z]+)', s[i:])
            if not m:          # \{ \} \% etc.
                i += 2
                continue
            nome = m.group(1)
            i += m.end()

            if nome in ('frac', 'dfrac', 'tfrac'):
                a, i = _ler_arg(s, i)
                b, i = _ler_arg(s, i)
                out.append(f' {_latex_expr_para_fala(a)} sobre {_latex_expr_para_fala(b)} ')

            elif nome == 'sqrt':
                indice = None
                if i < len(s) and s[i] == '[':
                    fim = s.find(']', i)
                    indice = s[i + 1:fim]
                    i = fim + 1
                a, i = _ler_arg(s, i)
                corpo = _latex_expr_para_fala(a)
                if indice == '3':
                    out.append(f' raiz cúbica de {corpo} ')
                elif indice:
                    out.append(f' raiz de índice {indice} de {corpo} ')
                else:
                    out.append(f' raiz quadrada de {corpo} ')

            elif nome in ('int', 'sum', 'prod'):
                baixo, cima, i = _ler_limites(s, i)
                palavra = {'int': 'integral', 'sum': 'somatório', 'prod': 'produtório'}[nome]
                if baixo is not None and cima is not None:
                    out.append(f' {palavra} de {_latex_expr_para_fala(baixo)} '
                               f'até {_latex_expr_para_fala(cima)} de ')
                else:
                    out.append(f' {palavra} de ')

            elif nome == 'lim':
                baixo, _, i = _ler_limites(s, i)
                if baixo:
                    out.append(f' limite quando {_latex_expr_para_fala(baixo)} de ')
                else:
                    out.append(' limite de ')

            elif nome in _TEXTO_PURO:
                a, i = _ler_arg(s, i)
                out.append(f' {a} ')

            else:
                out.append(f' {_SIMBOLOS.get(nome, nome)} ')

        elif c == '^':
            a, i = _ler_arg(s, i + 1)
            e = _latex_expr_para_fala(a)
            if e == '2':
                out.append(' ao quadrado ')
            elif e == '3':
                out.append(' ao cubo ')
            else:
                out.append(f' elevado a {e} ')

        elif c == '_':
            a, i = _ler_arg(s, i + 1)
            out.append(f' sub {_latex_expr_para_fala(a)} ')

        elif c in '{}':
            out.append(' ')
            i += 1

        elif c in _OPERADORES:
            out.append(f' {_OPERADORES[c]} ')
            i += 1

        else:
            out.append(c)
            i += 1

    texto = ''.join(out)
    texto = re.sub(r'(\d)\.(\d)', r'\1 vírgula \2', texto)  # 3.14 -> 3 vírgula 14
    return re.sub(r'\s+', ' ', texto).strip()


def traduzir_latex_para_voz(texto):
    """Troca as fórmulas LaTeX do texto por uma versão falada em português."""
    if not texto:
        return ''

    def trocar(m):
        expr = next(g for g in m.groups() if g is not None)
        return f' {_latex_expr_para_fala(expr)} '

    texto = _PADRAO_LATEX.sub(trocar, texto)
    texto = re.sub(r'\s+([.,;!?])', r'\1', texto)   # "h ." -> "h."
    return re.sub(r'[ \t]{2,}', ' ', texto).strip()

def perguntar_ia(texto):
    """Envia pergunta para o Gemini e retorna a resposta."""
    try:
        resposta = client.models.generate_content(
            model=model_name,
            contents=texto,
            config={'system_instruction': system_instruction}
        )
        return resposta.text.strip()
    except Exception as e:
        push_evento("log", {"tag": "ERR", "msg": f"Erro IA: {str(e)}"})
        return f"Erro ao consultar IA: {str(e)}"

# =========================
# ROTAS DE AUTENTICAÇÃO
# =========================
REMEMBER_DIAS = 30
SENHA_MIN = 8
DUMMY_HASH = hasher.hash('senha-falsa-para-igualar-tempo')

def _agora():
    return datetime.utcnow()

def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

def _criar_remember_token(conn, user_id):
    token = secrets.token_urlsafe(32)
    execute_sql(conn,
        'INSERT INTO remember_tokens (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)',
        (user_id, _hash_token(token),
         (_agora() + timedelta(days=REMEMBER_DIAS)).isoformat(), _agora().isoformat()))
    return token

@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    dados = request.get_json(silent=True) or {}
    email = (dados.get('email') or '').strip().lower()
    password = dados.get('password') or ''
    nome = (dados.get('nome') or '').strip() or None

    if not email or '@' not in email:
        return jsonify({'erro': 'Email inválido'}), 400
    if len(password) < SENHA_MIN:
        return jsonify({'erro': f'A senha precisa ter pelo menos {SENHA_MIN} caracteres'}), 400

    conn = get_db()
    try:
        try:
            cur = execute_sql(conn,
                'INSERT INTO users (email, password_hash, nome, created_at) VALUES (?, ?, ?, ?)',
                (email, hasher.hash(password), nome, _agora().isoformat()))
        except sqlite3.IntegrityError:
            return jsonify({'erro': 'Email já cadastrado'}), 409
        return jsonify({'id': cur.lastrowid, 'email': email, 'nome': nome}), 201
    finally:
        conn.close()

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    dados = request.get_json(silent=True) or {}
    email = (dados.get('email') or '').strip().lower()
    password = dados.get('password') or ''
    lembrar = bool(dados.get('lembrar'))

    if not email or not password:
        return jsonify({'erro': 'Email e senha são obrigatórios'}), 400

    conn = get_db()
    try:
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        if not user:
            try:
                hasher.verify(DUMMY_HASH, password)  # iguala o tempo de resposta
            except Exception:
                pass
            return jsonify({'erro': 'Credenciais inválidas'}), 401

        try:
            hasher.verify(user['password_hash'], password)
        except Exception:
            return jsonify({'erro': 'Credenciais inválidas'}), 401

        resposta = {'id': user['id'], 'email': user['email'], 'nome': user['nome']}
        if lembrar:  # só cria token se o usuário pediu
            resposta['token'] = _criar_remember_token(conn, user['id'])
        return jsonify(resposta), 200
    finally:
        conn.close()

@app.route('/api/auth/remember-me', methods=['POST'])
def auth_remember_me():
    dados = request.get_json(silent=True) or {}
    token = dados.get('token')
    if not token:
        return jsonify({'autenticado': False}), 401

    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM remember_tokens WHERE token_hash = ? AND expires_at > ?',
            (_hash_token(token), _agora().isoformat())).fetchone()
        if not row:
            return jsonify({'autenticado': False}), 401

        user = conn.execute('SELECT * FROM users WHERE id = ?', (row['user_id'],)).fetchone()
        if not user:
            return jsonify({'autenticado': False}), 401

        # rotação: o token usado é apagado e um novo é emitido
        execute_sql(conn, 'DELETE FROM remember_tokens WHERE id = ?', (row['id'],))
        novo = _criar_remember_token(conn, user['id'])
        return jsonify({'autenticado': True, 'id': user['id'], 'email': user['email'],
                        'nome': user['nome'], 'token': novo}), 200
    finally:
        conn.close()

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    dados = request.get_json(silent=True) or {}
    token = dados.get('token')
    conn = get_db()
    try:
        if token:
            execute_sql(conn, 'DELETE FROM remember_tokens WHERE token_hash = ?', (_hash_token(token),))
        return jsonify({'mensagem': 'Logout efetuado'}), 200
    finally:
        conn.close()


# =========================
# ROTAS FLASK EXISTENTES
# =========================

@app.route('/mensagem', methods=['POST'])
def mensagem():
    dados = request.get_json(silent=True) or {}
    texto = dados.get('texto', '').strip()

    if not texto:
        return jsonify({'texto': '', 'audio': None, 'modo': 'vazio'})

    push_evento("log", {"tag": "GEM", "msg": "Gerando resposta..."})
    try:
        resposta = perguntar_ia(texto)
        push_evento("log", {"tag": "TTS", "msg": "Sintetizando áudio..."})
        audio_b64 = gerar_audio(resposta)
        return jsonify({'texto': resposta, 'audio': audio_b64, 'modo': 'padrao'})
    except Exception as e:
        push_evento("log", {"tag": "ERR", "msg": f"Erro na geração: {str(e)}"})
        return jsonify({'texto': None, 'audio': None, 'modo': 'erro', 'erro': str(e)})

@app.route('/modo', methods=['POST'])
def alternar_modo():
    global modo_atual, voz_thread, voz_ativa

    dados = request.json
    novo_modo = dados.get('modo', 'texto')

    if novo_modo == modo_atual:
        return jsonify({'modo': modo_atual})

    modo_atual = novo_modo
    push_evento("log", {"tag": "SYS", "msg": f"Modo alterado para: {novo_modo.upper()}"})

    if novo_modo == "voz":
        voz_ativa = True
        voz_thread = threading.Thread(target=loop_voz, daemon=True)
        voz_thread.start()
        push_evento("log", {"tag": "SYS", "msg": "Thread de voz iniciada."})
    else:
        voz_ativa = False
        push_evento("log", {"tag": "SYS", "msg": "Modo texto ativo."})

    return jsonify({'modo': modo_atual})

@app.route('/stream')
def stream():
    def gerador():
        client_queue = queue.Queue()
        sse_clients.append(client_queue)
        push_evento("log", {"tag": "SYS", "msg": "Cliente SSE conectado."})
        try:
            while True:
                msg = client_queue.get()
                yield f"data: {msg}\n\n"
        except GeneratorExit:
            sse_clients.remove(client_queue)

    return Response(gerador(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def loop_voz():
    """Loop principal do modo voz: captura áudio, reconhece fala, gera resposta via IA e fala."""
    global voz_ativa, modo_atual
    
    push_evento("log", {"tag": "SYS", "msg": "Loop de voz iniciado."})
    
    while voz_ativa:
        try:
            # Captura áudio do microfone
            data = audio_stream.read(1280, exception_on_overrun=False)
            vosk_queue.put(data)
            
            # Processa reconhecimento de fala
            if rec.AcceptWaveform(data):
                resultado = rec.Result()
                texto = json.loads(resultado)["text"]
                
                if texto.strip():
                    push_evento("log", {"tag": "FALA", "msg": f"Ouvido: {texto}"})
                    
                    # Envia para a IA
                    resposta = perguntar_ia(texto)
                    push_evento("log", {"tag": "TTS", "msg": "Sintetizando áudio..."})
                    
                    # Gera áudio da resposta
                    audio_b64 = gerar_audio(resposta)
                    if audio_b64:
                        reproduzir_audio_b64(audio_b64)
                        push_evento("stream_audio_chunk", {"audio": audio_b64, "indice": 0})
                    
                    # Pequena pausa após resposta
                    time.sleep(0.5)
        except Exception as e:
            push_evento("log", {"tag": "ERR", "msg": f"Erro no loop de voz: {str(e)}"})
            time.sleep(0.1)

if __name__ == '__main__':
    app.run(port=5001, threaded=True, use_reloader=False)