from ..state import GraphState, TranscriptSegment, ConversationTurn
from datetime import datetime, timedelta
from typing import List
import re


# Common filler words and disfluencies to remove
FILLER_WORDS = {
    "um", "uh", "ah", "er", "hmm", "mhm", "uhm", "like", "you know",
    "i mean", "sort of", "kind of", "basically", "actually", "literally"
}

# Speaker label normalization mapping
SPEAKER_MAPPING = {
    # Doctor variants
    "dr": "Doctor",
    "doc": "Doctor",
    "doctor": "Doctor",
    "physician": "Doctor",
    "md": "Doctor",
    "provider": "Doctor",
    # Patient variants
    "pt": "Patient",
    "patient": "Patient",
    "client": "Patient",
    # Nurse variants
    "rn": "Nurse",
    "nurse": "Nurse",
    "lpn": "Nurse",
    "np": "Nurse",
    "nurse practitioner": "Nurse",
    # Assistant variants
    "ma": "Medical Assistant",
    "medical assistant": "Medical Assistant",
    "assistant": "Medical Assistant",
    "aide": "Medical Assistant",
    # Other
    "family": "Family Member",
    "relative": "Family Member",
    "visitor": "Family Member",
    "unknown": "Unknown",
    "unidentified": "Unknown"
}


def normalize_timestamp(timestamp_seconds: float) -> str:
    """
    Convert timestamp in seconds to ISO-8601 format.
    If already an ISO-8601 string, pass through unchanged.
    Returns None for None input.

    Args:
        timestamp_seconds: Timestamp in seconds from start, or ISO string

    Returns:
        ISO-8601 formatted timestamp string, or None
    """
    if timestamp_seconds is None:
        return None

    # If already an ISO string, pass through
    if isinstance(timestamp_seconds, str):
        try:
            datetime.fromisoformat(timestamp_seconds)
            return timestamp_seconds
        except ValueError:
            pass
        # Try to parse as a numeric string
        try:
            timestamp_seconds = float(timestamp_seconds)
        except (ValueError, TypeError):
            return timestamp_seconds

    # Use a reference date (session start would be better in production)
    reference_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    actual_time = reference_time + timedelta(seconds=timestamp_seconds)
    return actual_time.isoformat()


def standardize_speaker_label(speaker: str) -> str:
    """
    Standardize speaker labels to consistent format.

    Args:
        speaker: Raw speaker label

    Returns:
        Standardized speaker label
    """
    if not speaker:
        return "Unknown"

    # Normalize to lowercase for matching
    speaker_lower = speaker.lower().strip()

    # Check mapping
    if speaker_lower in SPEAKER_MAPPING:
        return SPEAKER_MAPPING[speaker_lower]

    # If no match, capitalize first letter of each word
    return speaker.title()


def remove_filler_words(text: str) -> str:
    """
    Remove common filler words and disfluencies from text.

    Args:
        text: Input text with fillers

    Returns:
        Cleaned text without fillers
    """
    if not text:
        return text

    # Convert to lowercase for matching, but preserve original case
    words = text.split()
    cleaned_words = []

    i = 0
    while i < len(words):
        word = words[i]
        word_lower = word.lower().strip('.,!?;:')

        # Check for multi-word fillers
        if i < len(words) - 1:
            two_word = f"{word_lower} {words[i+1].lower().strip('.,!?;:')}"
            if two_word in FILLER_WORDS:
                i += 2
                continue

        # Check single word fillers
        if word_lower not in FILLER_WORDS:
            cleaned_words.append(word)

        i += 1

    # Join and clean up extra spaces
    cleaned = ' '.join(cleaned_words)
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Remove multiple spaces
    cleaned = re.sub(r'\s+([.,!?;:])', r'\1', cleaned)  # Fix punctuation spacing

    return cleaned.strip()


def merge_adjacent_segments(segments: List[TranscriptSegment]) -> List[TranscriptSegment]:
    """
    Merge adjacent segments from the same speaker.

    Args:
        segments: List of transcript segments

    Returns:
        List of merged segments
    """
    if not segments:
        return segments

    merged = []
    current_segment = None

    for segment in segments:
        if current_segment is None:
            # First segment
            current_segment = segment.copy()
        elif (segment.get('speaker') == current_segment.get('speaker') and
              segment.get('speaker') is not None):
            # Same speaker - merge
            current_segment['end'] = segment['end']
            current_segment['raw_text'] += ' ' + segment['raw_text']

            # Merge cleaned text if available
            if current_segment.get('cleaned_text') and segment.get('cleaned_text'):
                current_segment['cleaned_text'] += ' ' + segment['cleaned_text']

            # Merge uncertainties
            if segment.get('uncertainties'):
                current_uncertainties = current_segment.get('uncertainties', [])
                current_segment['uncertainties'] = current_uncertainties + segment['uncertainties']
        else:
            # Different speaker - save current and start new
            merged.append(current_segment)
            current_segment = segment.copy()

    # Don't forget the last segment
    if current_segment is not None:
        merged.append(current_segment)

    return merged


def normalize_transcript_node(state: GraphState) -> GraphState:
    """
    Normalize transcript segments:
    - Convert timestamps to ISO-8601 format
    - Standardize speaker labels (Doctor, Patient, Nurse, etc.)
    - Merge adjacent segments from the same speaker
    - Remove filler words and disfluencies

    Args:
        state: Current graph state with new_segments

    Returns:
        Updated state with normalized conversation_log
    """
    new_segments = state.get('new_segments', [])

    if not new_segments:
        # No new segments to process
        state['controls']['trace_log'].append({
            'node': 'normalize_transcript',
            'action': 'skipped',
            'reason': 'no_new_segments',
            'timestamp': datetime.now().isoformat()
        })
        return state

    # Step 1: Normalize each segment
    normalized_segments = []
    for segment in new_segments:
        normalized_seg = segment.copy()

        # Standardize speaker label
        if segment.get('speaker'):
            normalized_seg['speaker'] = standardize_speaker_label(segment['speaker'])

        # Clean the text (remove fillers)
        if segment.get('raw_text'):
            cleaned = remove_filler_words(segment['raw_text'])
            normalized_seg['cleaned_text'] = cleaned

        normalized_segments.append(normalized_seg)

    # Step 2: Merge adjacent segments from same speaker
    merged_segments = merge_adjacent_segments(normalized_segments)

    # Step 3: Create conversation turns with ISO-8601 timestamps
    conversation_log = state.get('conversation_log', [])

    for segment in merged_segments:
        turn: ConversationTurn = {
            'timestamp': segment['start'],  # Keep numeric for now, can convert in presentation layer
            'segments': [segment]
        }
        conversation_log.append(turn)

    # Update state
    state['conversation_log'] = conversation_log

    # Clear new_segments since they've been processed
    state['new_segments'] = []

    # Log the operation
    state['controls']['trace_log'].append({
        'node': 'normalize_transcript',
        'action': 'normalized',
        'input_segments': len(new_segments),
        'output_segments': len(merged_segments),
        'merged_count': len(new_segments) - len(merged_segments),
        'timestamp': datetime.now().isoformat()
    })

    return state
