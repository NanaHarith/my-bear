import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = "https://api.sws.speechify.com"
API_KEY = os.getenv("SP_API_KEY")
VOICE_ID = "28c4d41d-8811-4ca0-9515-377d6ca2c715"

def stream_tts(text):
    try:
        response = requests.post(
            f"{API_BASE_URL}/v1/audio/stream",
            json={
                "input": f"<speak>{text}</speak>",
                "voice_id": VOICE_ID,
                "speed": 1.2,  # Increase speed (1.0 is normal)
                "sample_rate": 24000,
            },
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "Accept": "audio/mpeg"
            },
            stream=True
        )

        if response.ok:
            return response.iter_content(chunk_size=16384)
        else:
            print(f"Failed to generate audio: {response.status_code}")
            print(f"Response content: {response.content}")
            return None

    except Exception as e:
        print(f"Error in stream_tts: {str(e)}")
        return None