# audio_fingerprint.py

import numpy as np

FINGERPRINT_THRESHOLD = 0.8

def extract_features(audio_data):
    # Simple feature extraction: average amplitude in a few frequency bands
    fft = np.fft.fft(audio_data)
    freq = np.fft.fftfreq(len(audio_data))
    bands = [0, 500, 1000, 2000, 4000]  # Hz
    features = []
    for i in range(len(bands) - 1):
        band = fft[(freq >= bands[i]) & (freq < bands[i+1])]
        features.append(np.mean(np.abs(band)))
    return np.array(features)

def compare_fingerprints(fp1, fp2):
    if fp1 is None or fp2 is None:
        return 0
    return np.dot(fp1, fp2) / (np.linalg.norm(fp1) * np.linalg.norm(fp2))

class AudioFingerprinter:
    def __init__(self):
        self.last_output_fingerprint = None

    def process_output(self, audio_data):
        self.last_output_fingerprint = extract_features(audio_data)

    def check_input(self, audio_data):
        input_fingerprint = extract_features(audio_data)
        similarity = compare_fingerprints(input_fingerprint, self.last_output_fingerprint)
        return similarity > FINGERPRINT_THRESHOLD