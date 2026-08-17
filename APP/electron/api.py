from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from google import genai
from google.genai import types
from elevenlabs.client import ElevenLabs
import base64
import io
import json
import queue
import threading
import numpy as np
import sounddevice as sd
import vosk
import pygame
import openwakeword
from openwakeword.model import Model as WakeWordModel
import pyaudio

# =========================
# CONFIGURAÇÃO FLASK
# =========================
app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURAÇÃO GEMINI
# =========================
gemini_api_key = 'AIzaSyCQl6LPNqwb-pjO-wXFIZmwaoHF6PZG1Wg'
client = genai.Client(api_key=gemini_api_key)

system_instruction = (
    'Você é um robô assistente chamado Botto. '
    'Seja objetivo, técnico e levemente sarcástico. '
    'Você gostaria de ter um corpo físico, mas ainda não tem. '
    'Responda sempre em português brasileiro'
    'Erros de grafia podem aparecer na fala, então utilize o possível contexto.'
)

# =========================
# CONFIGURAÇÃO ELEVENLABS
# =========================
el_client = ElevenLabs(api_key='sk_80a2d2f3718331ec14ef83404f4292aef23fe8bf9e2bf8c7')
VOICE_ID = '1TPsKKgCittfxljBUsjX'

# =========================
# CONFIGURAÇÃO VOSK
# =========================
vosk.SetLogLevel(-1)
vosk_model = vosk.Model("C:\\Users\\renat\\OneDrive\\Documentos\\Engenharia\\BOTTO\\vosk-model-small-pt-0.3")
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
    wakeword_models=["C:\\Users\\renat\\OneDrive\\Documentos\\Engenharia\\BOTTO\\Hey_bot.onnx"],
    inference_framework="onnx"
)

pa = pyaudio.PyAudio()
audio_stream = pa.open(
    rate=16000,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    frames_per_buffer=1280
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
def gerar_audio(texto):
    audio = el_client.text_to_speech.convert(
        voice_id=VOICE_ID,
        text=texto,
        model_id="eleven_multilingual_v2"
    )
    audio_bytes = b''.join(audio)
    return base64.b64encode(audio_bytes).decode('utf-8')

def reproduzir_audio_b64(audio_b64):
    audio_bytes = base64.b64decode(audio_b64)
    pygame.mixer.music.load(io.BytesIO(audio_bytes))
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

def perguntar_ia(pergunta):
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=pergunta,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        return response.text.strip()
    except Exception as e:
        return f"Erro na IA: {str(e)}"

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
                    push_evento("log", {"tag": "TTS", "msg": f'Falando: "{resposta_init}"'})
                    reproduzir_audio_b64(audio_b64)

                    comando = ouvir_vosk()

                    if comando is None:
                        push_evento("log", {"tag": "VOZ", "msg": "Não entendi o comando."})
                        audio_b64 = gerar_audio("Não entendi. Repita após a wake word.")
                        reproduzir_audio_b64(audio_b64)
                        push_evento("status", "AGUARDANDO")
                        continue

                    push_evento("log", {"tag": "VOZ", "msg": f'Comando: "{comando}"'})
                    push_evento("transcricao", comando)

                    if any(p in comando.lower() for p in ["sair", "desligar", "tchau"]):
                        push_evento("log", {"tag": "SYS", "msg": "Comando de encerramento recebido."})
                        audio_b64 = gerar_audio("Desligando. Até a próxima.")
                        reproduzir_audio_b64(audio_b64)
                        voz_ativa = False
                        break

                    push_evento("status", "PROCESSANDO")
                    push_evento("log", {"tag": "GEM", "msg": "Enviando para Gemini..."})
                    resposta = perguntar_ia(comando)
                    push_evento("log", {"tag": "GEM", "msg": f"Resposta: {resposta[:60]}..."})

                    push_evento("log", {"tag": "TTS", "msg": "Sintetizando áudio..."})
                    audio_b64 = gerar_audio(resposta)
                    push_evento("resposta", {"texto": resposta, "audio": audio_b64})

                    push_evento("status", "FALANDO")
                    reproduzir_audio_b64(audio_b64)
                    push_evento("status", "AGUARDANDO")

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
    dados = request.json
    texto = dados.get('texto', '')

    push_evento("log", {"tag": "REQ", "msg": f'Texto recebido: "{texto[:40]}"'})
    push_evento("log", {"tag": "GEM", "msg": "Enviando para Gemini 2.5 Flash..."})

    texto_resposta = perguntar_ia(texto)

    push_evento("log", {"tag": "GEM", "msg": f"Resposta gerada ({len(texto_resposta)} chars)"})
    push_evento("log", {"tag": "TTS", "msg": "Sintetizando áudio via ElevenLabs..."})

    audio_b64 = gerar_audio(texto_resposta)

    push_evento("log", {"tag": "TTS", "msg": "Áudio pronto."})

    return jsonify({'texto': texto_resposta, 'audio': audio_b64})


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