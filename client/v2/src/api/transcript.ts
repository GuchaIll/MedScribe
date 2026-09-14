import { apiFetch } from "./client";

export type TranscriptMessage = {
  id: string;
  speaker: string;
  content: string;
  timestamp: string;
  type: string;
};

/** LLM speaker reclassification. Returns the same messages with updated `speaker`. */
export async function reclassifyTranscript(
  messages: TranscriptMessage[],
): Promise<TranscriptMessage[]> {
  const res = await apiFetch<{ messages: TranscriptMessage[] }>("/transcript/reclassify", {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
  return res.messages;
}
