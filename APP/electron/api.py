from datetime import datetime

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from google import genai
from google.genai import types
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
import os
import sys

from kokoro import KPipeline

import soundfile as sf


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

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
    'Você é o Botto, assistente técnico sarcástico. '
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
    """Gera áudio Kokoro de um trecho e envia via SSE para o app reproduzir."""
    try:
        # Traduzir LaTeX para leitura em voz antes de sintetizar
        trecho_para_tts = traduzir_latex_para_voz(trecho.strip())
        
        # Tokenize the text using the tokenizer
        phonemes = kokoro_model.tokenizer.phonemize(trecho_para_tts, 'pt-br')
        tokens = kokoro_model.tokenizer.tokenize(phonemes)
        tokens_array = np.array(tokens).reshape(1, -1).astype(np.int64)
        
        # Get voice style and reshape to [1, 256] as expected by the model
        voice_style = kokoro_model.voices[0, 0, 0].reshape(1, -1).astype(np.float32)
        
        # Speed as float32 array
        speed = np.array([1.0], dtype=np.float32)
        
        # Run ONNX session directly
        audio_array = kokoro_model.sess.run(
            None,
            {
                'tokens': tokens_array,
                'style': voice_style,
                'speed': speed
            }
        )[0]
        
        audio_bytes = audio_array.tobytes()
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        push_evento("stream_audio_chunk", {"audio": audio_b64, "indice": indice})
    except Exception as e:
        push_evento("log", {"tag": "ERR", "msg": f"Erro TTS chunk {indice}: {str(e)}"})

def processar_latex(texto):
    """Processa texto convertendo equacoes LaTeX para renderizacao HTML.

    Converte:
    - $$equacao$$ ou [equacao] para block equations
    - $equacao$ para inline equations
    """
    import re
    
    # Substituir block equations $$...$$ ou \[...\]
    texto = re.sub(r'\$\$(.+?)\$\$', r'<div class="math-block">\1</div>', texto, flags=re.DOTALL)
    texto = re.sub(r'\\\[(.+?)\\\]', r'<div class="math-block">\1</div>', texto, flags=re.DOTALL)
    
    # Substituir inline $...$ (cuidado para nao capturar $$)
    texto = re.sub(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', r'<span class="math-inline">\1</span>', texto)
    
    return texto


def traduzir_latex_para_voz(texto):
    _SIMBOLOS = {
    'alpha': 'alfa', 'beta': 'beta', 'gamma': 'gama', 'delta': 'delta',
    'Delta': 'delta', 'epsilon': 'épsilon', 'theta': 'teta', 'lambda': 'lâmbda',
    'mu': 'mi', 'pi': 'pi', 'sigma': 'sigma', 'omega': 'ômega', 'rho': 'rô',
    'phi': 'fi', 'tau': 'tau',
    'times': 'vezes', 'cdot': 'vezes', 'div': 'dividido por',
    'pm': 'mais ou menos', 'leq': 'menor ou igual a', 'le': 'menor ou igual a',
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


def _ler_arg(s, i):
    """Lê um argumento LaTeX a partir de i: {grupo}, \\comando ou 1 caractere."""
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
    """Lê _baixo e ^cima (em qualquer ordem) depois de \\int, \\sum, \\lim."""
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
    """Converte o conteúdo de uma expressão LaTeX em texto falado (pt-BR)."""
    s = re.sub(r'\\(left|right|displaystyle|bigg?|Bigg?)(?![a-zA-Z])', '', s)
    s = re.sub(r'\\[,;:! ]', ' ', s)
    s = re.sub(r'\^\s*\{?\\circ\}?', ' graus ', s)

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


_PADRAO_LATEX = re.compile(
    r'\$\$(.+?)\$\$'                    # $$ ... $$
    r'|\\\[(.+?)\\\]'                   # \[ ... \]
    r'|\\\((.+?)\\\)'                   # \( ... \)
    r'|(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)',  # $ ... $
    re.DOTALL
)


def traduzir_latex_para_voz(texto):
    """Troca as equações LaTeX do texto por leitura em português; o resto fica intacto."""
    def trocar(m):
        expr = next(g for g in m.groups() if g is not None)
        return f' {_latex_expr_para_fala(expr)} '

    texto = _PADRAO_LATEX.sub(trocar, texto)
    return re.sub(r'[ \t]{2,}', ' ', texto).strip()


def perguntar_ia(pergunta):
    """Retorna resposta completa — usado no modo voz."""
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=pergunta,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=2000,
                temperature=0.5,
            )
        )
        return response.text.strip()
    except Exception as e:
        return f"Erro na comunicação com a IA: {str(e)}"


def perguntar_ia_stream(pergunta, on_token, on_done):
    """Streaming — chama on_token a cada chunk e on_done com o texto completo."""
    try:
        texto_completo = ""
        for chunk in client.models.generate_content_stream(
            model=model_name,
            contents=pergunta,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=2000,
                temperature=0.5,
            )
        ):
            if chunk.text:
                texto_completo += chunk.text
                on_token(chunk.text)
        on_done(texto_completo)
    except Exception as e:
        on_done(f"Erro na comunicação com a IA: {str(e)}")

def ouvir_vosk():
    push_evento("status", "OUVINDO")
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                           channels=1, callback=vosk_callback):
        while True:
            data = vosk_queue.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                texto = result.get("text", "").strip()
                if texto:
                    return texto
                else:
                    return None

# =========================
# THREAD: MODO VOZ
# =========================
def loop_voz():
    global voz_ativa
    primeira_vez = True
    push_evento("log", {"tag": "VOZ", "msg": "Loop de wake word iniciado."})

    try:
        while voz_ativa:
            audio = audio_stream.read(1280, exception_on_overflow=False)
            audio_np = np.frombuffer(audio, dtype=np.int16)
            prediction = wakeword_model.predict(audio_np)

            for word, score in prediction.items():
                if score > 0.5 and voz_ativa:
                    push_evento("log", {"tag": "WAKE", "msg": f"Wake word detectada! Score: {score:.2f}"})
                    push_evento("status", "WAKE WORD")

                    if primeira_vez:
                        resposta_init = "Online. O que deseja?"
                        primeira_vez = False
                    else:
                        resposta_init = "Sim?"

                    audio_b64 = gerar_audio(resposta_init)
                    if audio_b64:
                        push_evento("log", {"tag": "TTS", "msg": f'Falando: "{resposta_init}"'})
                        audio_b64 = gerar_audio(resposta_init, voz_idx=VOZES_PT.get(KOKORO_VOICE, 43))
                    else:
                        push_evento("log", {"tag": "ERR", "msg": "Falha ao gerar áudio inicial"})

                    comando = ouvir_vosk()

                    if comando is None:
                        push_evento("log", {"tag": "VOZ", "msg": "Não entendi o comando."})
                        audio_b64 = gerar_audio("Não entendi. Repita após a wake word.", voz_idx=VOZES_PT.get(KOKORO_VOICE, 43))
                    if audio_b64:
                        reproduzir_audio_b64(audio_b64)
                    else:
                        push_evento("log", {"tag": "ERR", "msg": "Falha ao gerar áudio não entendido"})
                        push_evento("status", "AGUARDANDO")
                        continue

                    push_evento("log", {"tag": "VOZ", "msg": f'Comando: "{comando}"'})
                    push_evento("transcricao", comando)

                    if any(p in comando.lower() for p in ["sair", "desligar", "tchau"]):
                        push_evento("log", {"tag": "SYS", "msg": "Comando de encerramento recebido."})
                        audio_b64 = gerar_audio("Desligando. Até a próxima.", voz_idx=VOZES_PT.get(KOKORO_VOICE, 43))
                    if audio_b64:
                        reproduzir_audio_b64(audio_b64)
                    else:
                        push_evento("log", {"tag": "ERR", "msg": "Falha ao gerar áudio desligando"})
                        voz_ativa = False
                        break

                    push_evento("status", "PROCESSANDO")
                    push_evento("log", {"tag": "GEM", "msg": "Enviando para Gemini..."})

                    texto_completo = ""

                    def on_token(token):
                        nonlocal texto_completo
                        texto_completo += token
                        push_evento("log", {"tag": "GEM_TOKEN", "msg": token})

                    def on_done(texto_final):
                        nonlocal texto_completo
                        texto_completo = texto_final
                        push_evento("log", {"tag": "GEM", "msg": f"Resposta: {texto_completo[:60]}..."})
                        audio_b64 = gerar_audio(texto_completo, voz_idx=VOZES_PT.get(KOKORO_VOICE, 43))
                        if audio_b64:
                            push_evento("resposta", {"texto": texto_completo, "audio": audio_b64})
                            reproduzir_audio_b64(audio_b64)
                        else:
                            push_evento("log", {"tag": "ERR", "msg": "Falha ao gerar áudio resposta"})
                        push_evento("status", "AGUARDANDO")

                    perguntar_ia_stream(comando, on_token=on_token, on_done=on_done)

    except Exception as e:
        push_evento("log", {"tag": "ERR", "msg": f"Erro no loop de voz: {str(e)}"})
    finally:
        push_evento("status", "AGUARDANDO")
        push_evento("log", {"tag": "VOZ", "msg": "Loop de wake word encerrado."})

# =========================
# ROTAS FLASK
# =========================




@app.route('/mensagem', methods=['POST'])
def mensagem():
    dados = request.get_json(silent=True) or {}
    texto = dados.get('texto', '').strip()

    if not texto:  # o aguardarFlask() manda '{}' só para testar se o servidor subiu
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


if __name__ == '__main__':
    app.run(port=5001, threaded=True, use_reloader=False)