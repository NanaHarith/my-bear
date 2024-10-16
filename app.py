import os
import io
from flask import Flask, render_template, send_from_directory, request, send_file, jsonify, Response
from flask_socketio import SocketIO, emit
from openai import OpenAI
import webrtcvad
import wave
import requests
import time
from streaming_tts import stream_tts
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = "https://api.sws.speechify.com"
API_KEY = os.getenv("SP_API_KEY")
VOICE_ID = "28c4d41d-8811-4ca0-9515-377d6ca2c715"

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
conversation_history = []
conversation_active = False
vad = webrtcvad.Vad(3)  # Aggressiveness mode (0-3)

# Feature flag for streaming TTS
#USE_STREAMING_TTS = os.getenv('USE_STREAMING_TTS', 'True').lower() == 'true'
USE_STREAMING_TTS = False

SYSTEM_PROMPT = ("You are a calm, soothing assistant who speaks in a warm, empathetic, and gentle manner. "
                 "Your responses should make the user feel heard and understood, similar to a therapist. "
                 "Always provide thoughtful and reflective answers that help the user feel comforted.")

# Configurable cooldown period
COOLDOWN_PERIOD = float(os.getenv('COOLDOWN_PERIOD', 0))

# Flag to indicate if the system is currently speaking
is_speaking = False


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/beep')
def serve_beep():
    return send_from_directory('static/audio', 'beep.mp3', mimetype='audio/mpeg')


@socketio.on('connect')
def handle_connect():
    print('Client connected')


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')


last_response_time = 0


@socketio.on('transcription')
def handle_transcription(transcription):
    global conversation_active, last_response_time, is_speaking

    if is_speaking:
        print("System is speaking. Ignoring input.")
        return

    current_time = time.time()
    if current_time - last_response_time < COOLDOWN_PERIOD:
        print(f"Cooldown period active. Ignoring transcription: {transcription}")
        return

    print(f"Received transcription: {transcription}")

    if not conversation_active:
        conversation_active = True
        emit('conversation_started')

    process_command(transcription)
    last_response_time = current_time


def process_command(command):
    global is_speaking

    conversation_history.append({"role": "user", "content": command})
    is_speaking = True
    emit('system_speaking', {'speaking': True})

    if USE_STREAMING_TTS:
        stream_response(conversation_history)
    else:
        response = get_ai_response(conversation_history)
        emit('ai_response', {'text': response, 'is_final': True})
        audio_url = generate_audio(response)
        emit('audio_response', {'url': audio_url})

    is_speaking = False
    emit('system_speaking', {'speaking': False})


def stream_response(conversation):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation,
            stream=True
        )

        collected_messages = []
        # for chunk in response:
        #     if chunk.choices[0].delta.content is not None:
        #         content = chunk.choices[0].delta.content
        #         collected_messages.append(content)
        #         full_reply_content = ''.join(collected_messages).strip()
        #         emit('ai_response', {'text': full_reply_content, 'is_final': False})
        #
        #         audio_stream = stream_tts(content)
        #         if audio_stream:
        #             for audio_chunk in audio_stream:
        #                 emit('audio_chunk', {'chunk': audio_chunk})
        batched_content = ""
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                content = chunk.choices[0].delta.content
                batched_content += content
                if len(batched_content) >= 60:  # Send to TTS every 100 characters
                    audio_stream = stream_tts(batched_content)
                    if audio_stream:
                        for audio_chunk in audio_stream:
                            emit('audio_chunk', {'chunk': audio_chunk})
                    batched_content = ""
            full_reply_content = ''.join(collected_messages).strip()
            conversation_history.append({"role": "assistant", "content": full_reply_content})
            emit('ai_response', {'text': full_reply_content, 'is_final': True})

        # Emit a message indicating the entire response is complete
        emit('response_complete')
    except Exception as e:
        print(f"Error in stream_response: {str(e)}")
        emit('ai_response', {'text': "Sorry, there was an error processing your request.", 'is_final': True})
        emit('response_complete')

@socketio.on('audio_data')
def handle_audio_data(data):
    global is_speaking

    if is_speaking:
        return

    try:
        if is_speech(data):
            emit('speech_detected', {'detected': True})
        else:
            emit('speech_detected', {'detected': False})
    except Exception as e:
        print(f"Error in handle_audio_data: {str(e)}")
        emit('speech_detected', {'detected': False})

def is_speech(audio_data):
    try:
        audio = wave.open(io.BytesIO(audio_data), 'rb')
        sample_rate = audio.getframerate()
        audio_data = audio.readframes(audio.getnframes())

        frame_duration = 30  # in milliseconds
        frame_size = int(sample_rate * (frame_duration / 1000.0) * 2)
        offset = 0
        while offset + frame_size <= len(audio_data):
            frame = audio_data[offset:offset + frame_size]
            if vad.is_speech(frame, sample_rate):
                return True
            offset += frame_size
        return False
    except Exception as e:
        print(f"Error in is_speech: {str(e)}")
        return False


def get_ai_response(conversation):
    print("Sending request to OpenAI")
    try:
        full_conversation = [
                                {"role": "system", "content": SYSTEM_PROMPT}
                            ] + conversation

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=full_conversation,
            stream=True
        )

        collected_messages = []
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                collected_messages.append(chunk.choices[0].delta.content)
                full_reply_content = ''.join(collected_messages).strip()
                print(f"Emitting partial response: {full_reply_content}")
                emit('ai_response', {'text': full_reply_content, 'is_final': False})

        full_reply_content = ''.join(collected_messages).strip()
        conversation_history.append({"role": "assistant", "content": full_reply_content})
        return full_reply_content
    except Exception as e:
        print(f"Error in get_ai_response: {str(e)}")
        return "Sorry, there was an error processing your request."


def generate_audio(text):
    try:
        response = requests.post(f"{API_BASE_URL}/v1/audio/stream", json={
            "input": f"<speak>{text}</speak>",
            "voice_id": VOICE_ID,
        }, headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        })

        if response.ok:
            return f"/stream_audio?text={text}"
        else:
            print(f"Failed to generate audio: {response.status_code}")
            print(f"Response content: {response.content}")
            return None

    except Exception as e:
        print(f"Error in generate_audio: {str(e)}")
        return None


@app.route('/stream_audio')
def stream_audio():
    text = request.args.get('text')
    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        response = requests.post(f"{API_BASE_URL}/v1/audio/stream", json={
            "input": f"<speak>{text}</speak>",
            "voice_id": VOICE_ID,
        }, headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        })

        if response.ok:
            audio_stream = io.BytesIO(response.content)
            return send_file(audio_stream, mimetype='audio/mpeg')
        else:
            return jsonify({"error": "Failed to stream audio"}), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    socketio.run(app, allow_unsafe_werkzeug=True, debug=True)