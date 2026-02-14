#!/usr/bin/env python3
"""
Audio Question Detector and Answering System

This program captures audio from a specific desktop application (routed via virtual audio cable),
transcribes it using Groq's Whisper API, detects questions, and answers them using Groq's LLM.

Setup Instructions:
1. Install VB-Audio Virtual Cable (free): https://vb-audio.com/Cable/
2. Route your target application's audio to the virtual cable:
   - In Windows: Sound Settings > App volume and device preferences > Set output to CABLE Input
   - Or use VoiceMeeter for more control
3. Set your default playback device to your speakers (so you can still hear)
4. Install dependencies: pip install sounddevice numpy python-dotenv groq pyttsx3
5. Create a .env file with your GROQ_API_KEY (get free from console.groq.com)
6. Run this program and select the virtual cable as the input device
"""

import sounddevice as sd
import numpy as np
import os
import sys
import time
import re
import logging
from io import BytesIO
from dotenv import load_dotenv
from groq import Groq
from collections import deque
import wave
import threading
import queue

# Optional TTS support
TTS_ENABLED = False
try:
    import pyttsx3
    TTS_ENABLED = True
except ImportError:
    print("Note: pyttsx3 not installed. Text-to-speech disabled. Install with: pip install pyttsx3")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Configuration
SAMPLE_RATE = 16000  # 16kHz is standard for speech recognition
CHANNELS = 1  # Mono audio
SILENCE_THRESHOLD = 0.01  # Amplitude threshold to detect silence
MIN_SPEECH_DURATION = 1.0  # Minimum seconds of non-silence to process
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# VAD-based chunking parameters
MIN_CHUNK_DURATION = 2       # Minimum seconds of speech before split
MAX_CHUNK_DURATION = 15      # Forced split if no silence detected
SILENCE_DURATION = 0.6       # Seconds of silence for split
SILENCE_WINDOW = 0.05        # 50ms window for silence detection
VAD_THRESHOLD = 0.008        # RMS threshold for silence

# Whisper prompt — hints for correct IT term recognition
WHISPER_PROMPT = (
    "Big Data, Python, JavaScript, TypeScript, React, Angular, Vue, Node.js, "
    "REST API, GraphQL, Docker, Kubernetes, DevOps, CI/CD, Git, GitHub, "
    "Machine Learning, Deep Learning, Neural Network, TensorFlow, PyTorch, "
    "SQL, NoSQL, MongoDB, PostgreSQL, Redis, AWS, Azure, Google Cloud, "
    "microservices, framework, backend, frontend, deploy, refactoring, "
    "algorithm, recursion, sprint, scrum, agile, waterfall"
)

# Question detection patterns - Ukrainian and English
QUESTION_WORDS_UKRAINIAN = [
    "що", "де", "коли", "чому", "як", "хто", "який", "яка", "яке", "які",
    "чи", "скільки", "котрий", "куди", "звідки", "навіщо", "відколи"
]

QUESTION_WORDS_ENGLISH = [
    "what", "where", "when", "why", "how", "who", "which", "whom",
    "can", "could", "would", "should", "is", "are", "do", "does", "did",
    "will", "shall", "may", "might", "must"
]

QUESTION_WORDS = QUESTION_WORDS_UKRAINIAN + QUESTION_WORDS_ENGLISH

# Optional: Keywords to filter questions (e.g., only answer programming-related questions)
# Leave empty to answer all questions
CONTEXT_KEYWORDS = []  # Empty list = respond to ALL recognized text


class AudioQuestionDetector:
    """Main class for audio capture, transcription, and question answering."""
    
    def __init__(self, device_index=None, enable_tts=False):
        """Initialize the detector with audio device and configuration."""
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY not found in .env file. Please add it.")
        
        self.client = Groq(api_key=GROQ_API_KEY)
        self.device_index = device_index
        self.enable_tts = enable_tts and TTS_ENABLED
        self.audio_queue = queue.Queue()
        self.is_running = False
        self.last_transcription = ""
        self.conversation_history = []
        self._sample_rate = SAMPLE_RATE  # Updated when starting

        # Cached VAD parameters (updated in start_listening)
        self._min_frames = int(SAMPLE_RATE * MIN_CHUNK_DURATION)
        self._max_frames = int(SAMPLE_RATE * MAX_CHUNK_DURATION)
        self._silence_frames = int(SAMPLE_RATE * SILENCE_DURATION)
        self._window_frames = int(SAMPLE_RATE * SILENCE_WINDOW)
        
        # Initialize TTS engine if enabled
        if self.enable_tts:
            try:
                self.tts_engine = pyttsx3.init()
                self.tts_engine.setProperty('rate', 150)
                self.tts_engine.setProperty('volume', 0.9)
            except Exception as e:
                logger.warning(f"Failed to initialize TTS: {e}")
                self.enable_tts = False
        
        logger.info("AudioQuestionDetector initialized")
    
    def audio_callback(self, indata, frames, time_info, status):
        """Callback function for audio stream."""
        if status:
            logger.warning(f"Audio callback status: {status}")
        
        # Copy audio data to queue for processing
        self.audio_queue.put(indata.copy())
    
    def save_audio_to_wav(self, audio_data, sample_rate):
        """Convert numpy array to WAV bytes for API upload."""
        buf = BytesIO()
        with wave.open(buf, 'wb') as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            audio_int16 = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        buf.seek(0)
        return buf
    
    def transcribe_audio(self, audio_data, sample_rate=None):
        """Transcribe audio with context and IT term hints."""
        if sample_rate is None:
            sample_rate = SAMPLE_RATE
        
        try:
            # Convert audio to WAV format
            wav_buffer = self.save_audio_to_wav(audio_data, sample_rate)
            wav_buffer.name = "audio.wav"  # Groq requires a filename
            
            # Build prompt: previous transcription + IT terms
            prompt = WHISPER_PROMPT
            if self.last_transcription:
                prev_context = self.last_transcription[-200:]
                prompt = prev_context + " " + WHISPER_PROMPT[:100]
            
            # Call Groq Whisper API
            transcription = self.client.audio.transcriptions.create(
                file=wav_buffer,
                model="whisper-large-v3",
                response_format="text",
                prompt=prompt,
                temperature=0.0  # More deterministic
            )
            
            result = transcription.strip() if transcription else ""
            
            # Save context for next call
            if result:
                self.last_transcription = result
            
            return result
        
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
    
    def correct_transcription(self, raw_text):
        """Fix garbled technical terms via LLM (conservative)."""
        try:
            correction = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": 
                        "You are a speech recognition text corrector.\n"
                        "Strict rules:\n"
                        "1. Fix ONLY individual words that are obviously garbled IT terms\n"
                        "2. NEVER add new words or sentences\n"
                        "3. NEVER delete words\n"
                        "4. NEVER explain or expand the text\n"
                        "5. The word count in your response must match the original\n"
                        "6. If the text is already correct, return it unchanged\n"
                        "Examples: 'paithan' → 'Python', 'rest apay' → 'REST API', 'dokker' → 'Docker'."},
                    {"role": "user", "content": raw_text}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                max_tokens=150
            )
            corrected = correction.choices[0].message.content.strip()
            
            # Length guard: reject if text changed by more than 50%
            if len(corrected) > len(raw_text) * 1.5 or len(corrected) < len(raw_text) * 0.5:
                logger.warning("Correction rejected (text changed too much)")
                return raw_text
            
            return corrected
        except Exception as e:
            logger.warning(f"Correction error: {e}")
            return raw_text
    
    def is_question(self, text):
        """Detect if the text contains a question"""
        if not text:
            return False
        
        # Respond to all recognized text
        return True
    
    def is_relevant_question(self, text):
        """Check if question is relevant based on context keywords."""
        if not CONTEXT_KEYWORDS:
            return True  # No filtering, accept all questions
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in CONTEXT_KEYWORDS)
    
    def answer_question(self, question):
        """Generate an answer using Groq's LLM with conversation history."""
        try:
            system_prompt = (
                "You are a helpful AI assistant that answers any questions. "
                "ALWAYS respond in Ukrainian, even if the question is in English. "
                "Give concise, clear answers (2-3 sentences maximum). "
                "If the question is about technology/programming, you may include a code example. "
                "Explain in simple terms so the person can quickly understand and respond in conversation. "
                "Take into account the context of previous questions and answers in the conversation."
            )
            
            # Build messages with conversation history
            messages = [{"role": "system", "content": system_prompt}]
            
            for prev_q, prev_a in self.conversation_history[-10:]:
                messages.append({"role": "user", "content": prev_q})
                messages.append({"role": "assistant", "content": prev_a})
            
            messages.append({"role": "user", "content": question})
            
            chat_completion = self.client.chat.completions.create(
                messages=messages,
                model="llama-3.3-70b-versatile",
                temperature=0.7,
                max_tokens=300,
                top_p=0.9
            )
            
            answer = chat_completion.choices[0].message.content.strip()
            
            # Save to conversation history
            self.conversation_history.append((question, answer))
            if len(self.conversation_history) > 10:
                self.conversation_history = self.conversation_history[-10:]
            
            return answer
        
        except Exception as e:
            logger.error(f"Answer generation error: {e}")
            return "Sorry, could not generate an answer at this time."
    
    def speak_answer(self, text):
        """Speak the answer using TTS (if enabled)."""
        if self.enable_tts and self.tts_engine:
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
            except Exception as e:
                logger.error(f"TTS error: {e}")
    
    def has_speech(self, audio_data, threshold=SILENCE_THRESHOLD):
        """Check if audio chunk contains speech (above silence threshold)."""
        rms = np.sqrt(np.dot(audio_data, audio_data) / len(audio_data))
        return rms > threshold
    
    def detect_silence_split(self, buffer):
        """Find silence-based split point in audio buffer."""
        buf_len = len(buffer)
        if buf_len < self._min_frames:
            return None
        
        search_start = self._min_frames
        search_end = buf_len - self._silence_frames
        
        if search_start >= search_end:
            return None
        
        pos = search_start
        sf = self._silence_frames
        wf = self._window_frames
        threshold_sq = VAD_THRESHOLD * VAD_THRESHOLD
        while pos < search_end:
            window = buffer[pos:pos + sf]
            mean_sq = np.dot(window, window) / sf
            if mean_sq < threshold_sq:
                return pos + sf
            pos += wf
        
        return None
    
    def process_audio_chunk(self, audio_chunk):
        """Process a chunk of audio: transcribe, detect questions, and answer."""
        if not self.has_speech(audio_chunk):
            logger.debug("Silent chunk detected, skipping...")
            return
        
        chunk_duration = len(audio_chunk) / self._sample_rate
        logger.info(f"Processing audio ({chunk_duration:.1f}s)...")
        
        raw_transcription = self.transcribe_audio(audio_chunk, self._sample_rate)
        
        if not raw_transcription:
            logger.debug("No transcription generated")
            return
        
        logger.info(f"Raw text: {raw_transcription}")
        
        # LLM correction of garbled terms
        transcription = self.correct_transcription(raw_transcription)
        
        if transcription != raw_transcription:
            logger.info(f"Corrected: {transcription}")
        
        logger.info(f"Transcription: {transcription}")
        
        # Detect if it's a question
        if self.is_question(transcription):
            logger.info("Text detected, generating answer...")
            
            if not self.is_relevant_question(transcription):
                pass
            
            # Generate answer
            logger.info("Generating answer...")
            answer = self.answer_question(transcription)
            
            # Output answer
            print("\n" + "="*60)
            print(f"TEXT: {transcription}")
            print(f"ANSWER: {answer}")
            print("="*60 + "\n")
            
            # Speak answer if TTS is enabled
            if self.enable_tts:
                self.speak_answer(answer)
    
    def start_listening(self):
        """Start the main audio capture and processing loop with VAD-based chunking."""
        self.is_running = True
        
        # Get actual device sample rate
        try:
            device_info = sd.query_devices(self.device_index, 'input')
            actual_sample_rate = int(device_info['default_samplerate'])
            logger.info(f"Using sample rate: {actual_sample_rate} Hz")
        except Exception as e:
            logger.warning(f"Failed to get device sample rate: {e}")
            actual_sample_rate = SAMPLE_RATE

        # Update cached parameters for actual sample rate
        self._sample_rate = actual_sample_rate
        self._min_frames = int(actual_sample_rate * MIN_CHUNK_DURATION)
        self._max_frames = int(actual_sample_rate * MAX_CHUNK_DURATION)
        self._silence_frames = int(actual_sample_rate * SILENCE_DURATION)
        self._window_frames = int(actual_sample_rate * SILENCE_WINDOW)
        
        logger.info(f"Starting audio capture from device {self.device_index}")
        logger.info(f"Mode: VAD chunking ({MIN_CHUNK_DURATION}-{MAX_CHUNK_DURATION}s)")
        logger.info(f"Sample rate: {actual_sample_rate}Hz")
        logger.info(f"TTS: {'Enabled' if self.enable_tts else 'Disabled'}")
        logger.info("Press Ctrl+C to stop\n")
        
        try:
            with sd.InputStream(
                device=self.device_index,
                channels=CHANNELS,
                samplerate=actual_sample_rate,
                callback=self.audio_callback,
                blocksize=int(actual_sample_rate * 0.1)
            ):
                # List instead of np.append — O(1) append
                buffer_chunks = []
                buffer_len = 0
                
                while self.is_running:
                    try:
                        audio_data = self.audio_queue.get(timeout=1.0)
                        flat = audio_data.flatten()
                        buffer_chunks.append(flat)
                        buffer_len += len(flat)
                        
                        if buffer_len >= self._min_frames:
                            buffer = np.concatenate(buffer_chunks)
                            split_point = self.detect_silence_split(buffer)
                            
                            if split_point is not None:
                                chunk = buffer[:split_point]
                                rest = buffer[split_point:]
                                buffer_chunks = [rest] if len(rest) > 0 else []
                                buffer_len = len(rest)
                                
                                threading.Thread(
                                    target=self.process_audio_chunk,
                                    args=(chunk,),
                                    daemon=True
                                ).start()
                            elif buffer_len >= self._max_frames:
                                logger.warning("Forced split (max duration)")
                                chunk = buffer[:self._max_frames]
                                rest = buffer[self._max_frames:]
                                buffer_chunks = [rest] if len(rest) > 0 else []
                                buffer_len = len(rest)
                                
                                threading.Thread(
                                    target=self.process_audio_chunk,
                                    args=(chunk,),
                                    daemon=True
                                ).start()
                            else:
                                buffer_chunks = [buffer]
                    
                    except queue.Empty:
                        continue
        
        except KeyboardInterrupt:
            logger.info("\nStopping...")
        except Exception as e:
            logger.error(f"Error in audio stream: {e}")
        finally:
            self.is_running = False
            logger.info("Audio capture stopped")


def list_audio_devices():
    """List all available audio input devices."""
    print("\n" + "="*60)
    print("Available Audio Input Devices:")
    print("="*60)
    
    devices = sd.query_devices()
    input_devices = []
    
    for idx, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            input_devices.append((idx, device))
            print(f"[{idx}] {device['name']}")
            print(f"    Channels: {device['max_input_channels']}, Sample Rate: {device['default_samplerate']}Hz")
    
    print("="*60 + "\n")
    return input_devices


def select_audio_device():
    """Prompt user to select an audio input device."""
    input_devices = list_audio_devices()
    
    if not input_devices:
        logger.error("No input devices found!")
        sys.exit(1)
    
    while True:
        try:
            choice = input("Enter the device index to capture from (or 'q' to quit): ").strip()
            
            if choice.lower() == 'q':
                sys.exit(0)
            
            device_idx = int(choice)
            
            # Validate device index
            if any(idx == device_idx for idx, _ in input_devices):
                return device_idx
            else:
                print(f"Invalid device index. Please choose from the list above.")
        
        except ValueError:
            print("Invalid input. Please enter a number or 'q' to quit.")


def main():
    """Main entry point."""
    print("\n" + "="*60)
    print("Audio Question Detector and Answering System")
    print("="*60)
    print("\nSetup Requirements:")
    print("1. Route your target app's audio to a virtual audio cable")
    print("2. Ensure GROQ_API_KEY is set in your .env file")
    print("3. Select the virtual cable input device below")
    print()
    
    # Check for API key
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY not found in .env file!")
        print("\nPlease create a .env file with your Groq API key:")
        print("GROQ_API_KEY=your_api_key_here")
        print("\nGet a free API key at: https://console.groq.com/")
        sys.exit(1)
    
    # Select audio device
    device_idx = select_audio_device()
    
    # Ask about TTS
    if TTS_ENABLED:
        tts_choice = input("\nEnable text-to-speech for answers? (y/n, default=n): ").strip().lower()
        enable_tts = tts_choice == 'y'
    else:
        enable_tts = False
    
    # Create and start detector
    try:
        detector = AudioQuestionDetector(device_index=device_idx, enable_tts=enable_tts)
        detector.start_listening()
    except Exception as e:
        logger.error(f"Failed to start detector: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
