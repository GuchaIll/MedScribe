import { apiRawFetch } from "./client";

let _currentAudio: HTMLAudioElement | null = null;

/**
 * Speak text via the backend TTS endpoint, falling back to browser SpeechSynthesis.
 * Always cancels any previously playing utterance first.
 */
export async function speakText(text: string): Promise<void> {
  if (_currentAudio) {
    _currentAudio.pause();
    _currentAudio = null;
  }
  try {
    const res = await apiRawFetch("/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      _currentAudio = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (_currentAudio === audio) _currentAudio = null;
      };
      await audio.play();
      return;
    }
  } catch {
    /* fall through */
  }
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.9;
    window.speechSynthesis.speak(u);
  }
}
