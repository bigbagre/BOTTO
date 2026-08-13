from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
from elevenlabs.client import ElevenLabs
import base64
import io

app = Flask(__name__)
CORS(app)

gemini_api_key = 'AIzaSyCQl6LPNqwb-pjO-wXFIZmwaoHF6PZG1Wg'
client = genai.Client(api_key=gemini_api_key)

el_client = ElevenLabs(api_key='sk_80a2d2f3718331ec14ef83404f4292aef23fe8bf9e2bf8c7')

system_instruction = (
    'Você é um robô assistente chamado Botto. '
    'Seja objetivo, técnico e levemente sarcástico. '
    'Responda sempre em português brasileiro.'
)

@app.route('/mensagem', methods=['POST'])
def mensagem():
    dados = request.json
    texto = dados.get('texto', '')

    resposta = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=texto,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction
        )
    )
    texto_resposta = resposta.text.strip()

    audio = el_client.text_to_speech.convert(
        voice_id='1TPsKKgCittfxljBUsjX',
        text=texto_resposta,
        model_id='eleven_multilingual_v2'
    )
    audio_bytes = b''.join(audio)
    audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

    return jsonify({
        'texto': texto_resposta,
        'audio': audio_b64
    })

if __name__ == '__main__':
    app.run(port=5001)