import os
import queue
import sounddevice as sd
import vosk
import sys
import pygame
import json
import numpy as np
import openwakeword
from openwakeword.model import Model as WakeWordModel
import pyaudio
from google import genai
from google.genai import types
from elevenlabs.client import ElevenLabs
from flask import Flask, request, jsonify
from flask_cors import CORS
import io
import threading
import base64
import time
from dotenv import load_dotenv
import os
from pathlib import Path

# =========================
# CONSTANTES
# =========================

USER_DIR = Path(__file__).resolve().parent
MODO_TEXTO = False

app = Flask(__name__)
CORS(app)

def iniciar_flask():
    app.run(port=5001, use_reloader=False)

load_dotenv()
gemini_key = os.environ["GEMINI_API_KEY"]
eleven_key = os.environ["ELEVENLABS_API_KEY"]

client = genai.Client(api_key=gemini_key)

system_instruction = (
    "Você é um robô assistente chamado Botto. "
    "Seja objetivo, técnico e levemente sarcástico."
    "Você gostaria de ter um corpo fisico, mas ainda não tem"
    "Responda sempre em português brasileiro, com frases curtas e impactantes. "
    "Erros de grafia podem aparecer na fala, então utilize o possível contexto."
)

# =========================
# CONFIGURAÇÃO VOSK
# =========================
model_path = "vosk-model-small-pt-0.3"
if not os.path.exists(model_path):
    print("Erro: Pasta do modelo Vosk não encontrada.")
    sys.exit(1)

vosk.SetLogLevel(-1)
vosk_model = vosk.Model(model_path)
rec = vosk.KaldiRecognizer(vosk_model, 16000)

q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

# =========================
# CONFIGURAÇÃO PYGAME
# =========================
pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)

# =========================
# CONFIGURAÇÃO OPENWAKEWORD
# =========================

openwakeword.utils.download_models()

wakeword_model = WakeWordModel(wakeword_models=[USER_DIR / "Hey_Jarvis.onnx"], inference_framework="onnx")

pa = pyaudio.PyAudio()
audio_stream = pa.open(
    rate=16000,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    frames_per_buffer=1280,
    input_device_index=1
)

el_client = ElevenLabs(api_key=eleven_key)

def falar(texto):
    print("Botto:", texto)
    audio = el_client.text_to_speech.convert(
        voice_id="3JdeqiQnLxoeVurZP9dp",
        text=texto,
        model_id="eleven_multilingual_v2"
    )
    audio_bytes = b"".join(audio)
    pygame.mixer.music.load(io.BytesIO(audio_bytes))
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

# =========================
# FUNÇÃO: OUVIR COM VOSK
# =========================
def ouvir():
    print("Escutando... (fale agora)")
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16',
                           channels=1, callback=callback):
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                texto = result.get("text", "").strip()
                if texto:
                    print("Você:", texto)
                    return texto
                else:
                    return None

 
# FUNÇÃO: PERGUNTAR AO GEMINI

def perguntar_ia(pergunta):
    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=pergunta,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        return response.text.strip()
    except Exception as e:
        return f"Erro na comunicação com a IA: {str(e)}"


# LOOP PRINCIPAL
 
# =========================
# LOOP PRINCIPAL
# =========================

@app.route('/mensagem', methods=['POST'])
def mensagem():
    dados = request.json
    texto = dados.get('texto', '')
    texto_resposta = perguntar_ia(texto)
    audio = el_client.text_to_speech.convert(
        voice_id="3JdeqiQnLxoeVurZP9dp",
        text=texto_resposta,
        model_id="eleven_multilingual_v2"
    )
    audio_bytes = b''.join(audio)
    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
    return jsonify({'texto': texto_resposta, 'audio': audio_b64})

if __name__ == "__main__":
    threading.Thread(target=iniciar_flask, daemon=True).start()
    time.sleep(1.5)
    falar("Botto online. Aguardando wake word.")
    print("\n=== Escutando wake word 'Hey Bot' ===")

    if MODO_TEXTO:
        print("\n=== MODO TEXTO ATIVADO ===")
        print("Digite sua mensagem e pressione ENTER. Digite 'sair' para encerrar.\n")
        while True:
            try:
                comando = input("Você: ").strip()
                if not comando:
                    continue
                if any(p in comando.lower() for p in ["sair", "desligar", "tchau"]):
                    print("Botto: Desligando. Até a próxima.")
                    break
                resposta = perguntar_ia(comando)
                falar(resposta)
            except KeyboardInterrupt:
                print("\nEncerrando...")
                break

    else:
        primeira_vez = True
        try:
            while True:
                audio = audio_stream.read(1280, exception_on_overflow=False)
                audio_np = np.frombuffer(audio, dtype=np.int16)
                prediction = wakeword_model.predict(audio_np)

                for word, score in prediction.items():
                    if score > 0.5:
                        print(f">>> Wake word detectada! Score: {score:.2f}")

                        if primeira_vez:
                            falar("Online. O que deseja?")
                            primeira_vez = False
                        else:
                            falar("Sim?")

                        comando = ouvir()

                        if comando is None:
                            falar("Não entendi. Repita após a wake word.")
                            continue

                        if any(p in comando.lower() for p in ["sair", "desligar", "tchau"]):
                            falar("Desligando. Até a próxima.")
                            raise SystemExit

                        resposta = perguntar_ia(comando)
                        falar(resposta)

        except (KeyboardInterrupt, SystemExit):
            print("\nEncerrando...")
        finally:
            audio_stream.stop_stream()
            audio_stream.close()
            pa.terminate()
            print("Sistema desligado com segurança.")