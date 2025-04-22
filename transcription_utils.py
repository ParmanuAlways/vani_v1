import torch
import soundfile as sf
import numpy as np
import torchaudio.functional as F
import os
import asyncio
from pathlib import Path
from transformers import WhisperProcessor, WhisperForConditionalGeneration
from pyannote.audio import Pipeline
from typing import Dict, List, Tuple, Any, Optional

# Initialize models globally
MODEL_NAME = "jlvdoorn/whisper-large-v3-atco2-asr"
processor = WhisperProcessor.from_pretrained(MODEL_NAME)
model = WhisperForConditionalGeneration.from_pretrained(MODEL_NAME)

# Initialize pipeline as None
pipeline = None

# Default path to pyannote configuration file
DEFAULT_PYANNOTE_CONFIG_PATH = "models/pyannote_diarization_config.yaml"

def load_pipeline_from_pretrained(path_to_config):
    """
    Load pyannote pipeline from a local configuration file.
    
    Args:
        path_to_config (str): Path to the configuration file
    
    Returns:
        Pipeline: The loaded pipeline or None if loading failed
    """
    try:
        print(f"DEBUG: Starting load_pipeline_from_pretrained with path_to_config={path_to_config}")
        
        if not os.path.exists(path_to_config):
            print(f"DEBUG: Configuration file not found: {path_to_config}")
            return None
            
        path_to_config = Path(path_to_config)
        
        print(f"DEBUG: Loading pyannote pipeline from {path_to_config}...")
        
        # The paths in the config are relative to the current working directory
        # so we need to change the working directory to the model path
        # and then change it back
        
        cwd = Path.cwd().resolve()  # Store current working directory
        print(f"DEBUG: Current working directory: {cwd}")
        
        # First .parent is the folder of the config, second .parent is the folder containing the 'models' folder
        try:
            cd_to = path_to_config.parent.parent.resolve()
            print(f"DEBUG: Attempting to change working directory to {cd_to}")
            os.chdir(cd_to)
        except Exception as e:
            print(f"DEBUG: Error changing directory: {str(e)}")
            # If we can't change to parent.parent, just try using the direct parent
            try:
                cd_to = path_to_config.parent.resolve()
                print(f"DEBUG: Attempting to change working directory to {cd_to} (fallback)")
                os.chdir(cd_to)
            except Exception as e2:
                print(f"DEBUG: Error changing directory (fallback): {str(e2)}")
                return None
        
        try:
            print("DEBUG: Creating Pipeline instance")
            loaded_pipeline = Pipeline.from_pretrained(path_to_config)
            print("DEBUG: Pipeline created successfully")
        except Exception as e:
            print(f"DEBUG: Error creating pipeline: {str(e)}")
            import traceback
            print(traceback.format_exc())
            loaded_pipeline = None
        
        print(f"DEBUG: Changing working directory back to {cwd}")
        os.chdir(cwd)
        
        return loaded_pipeline
    except Exception as e:
        print(f"DEBUG: Unexpected error in load_pipeline_from_pretrained: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None

def split_audio(audio_data, sampling_rate, chunk_size=30):
    """
    Splits audio into 30-second chunks (or as specified).
    
    Parameters:
        audio_data (numpy.array): Audio waveform data.
        sampling_rate (int): Sampling rate of the audio.
        chunk_size (int): Maximum chunk length in seconds (default: 30s).

    Returns:
        list: List of audio chunks with timestamps.
    """
    chunk_samples = chunk_size * sampling_rate  # Convert seconds to samples
    total_samples = len(audio_data)
    
    chunks = []
    for start in range(0, total_samples, chunk_samples):
        end = min(start + chunk_samples, total_samples)
        chunk = audio_data[start:end]
        chunks.append({
            "audio": chunk, 
            "start_time": start / sampling_rate, 
            "end_time": end / sampling_rate
        })

    return chunks

def transcribe_audio_with_timestamps(audio_data, sampling_rate):
    """
    Transcribes long audio by splitting it into chunks and merging the results.
    """
    print(f"DEBUG: Starting transcribe_audio_with_timestamps with sampling_rate={sampling_rate}")
    
    # Convert to mono if stereo
    if len(audio_data.shape) > 1:
        print("DEBUG: Converting stereo to mono")
        audio_data = audio_data.mean(axis=1)

    # Resample the audio if needed
    if sampling_rate != 16000:
        print(f"DEBUG: Resampling audio from {sampling_rate}Hz to 16000Hz")
        audio_data = F.resample(torch.tensor(audio_data), orig_freq=sampling_rate, new_freq=16000).numpy()

    # Split audio into chunks
    audio_chunks = split_audio(audio_data, sampling_rate=16000, chunk_size=30)
    print(f"DEBUG: Split audio into {len(audio_chunks)} chunks")
    
    transcription_results = []

    for i, chunk in enumerate(audio_chunks):
        print(f"DEBUG: Processing chunk {i+1}/{len(audio_chunks)}")
        # Process the audio for the model
        inputs = processor(chunk["audio"], return_tensors="pt", sampling_rate=16000)

        # Generate transcription with timestamps
        with torch.no_grad():
            outputs = model.generate(inputs.input_features, return_timestamps=True)

        # Decode output with timestamps
        transcription = processor.batch_decode(outputs, output_offsets=True, skip_special_tokens=True)

        # Adjust timestamps relative to full audio
        for segment in transcription:
            for offset in segment["offsets"]:
                offset["timestamp"] = (
                    offset["timestamp"][0] + chunk["start_time"],  # Adjust start time
                    offset["timestamp"][1] + chunk["start_time"]   # Adjust end time
                )

        transcription_results.extend(transcription)
        print(f"DEBUG: Chunk {i+1} transcription complete")

    print(f"DEBUG: Transcription complete with {len(transcription_results)} segments")
    return transcription_results

def perform_diarization(audio_path, config_path=None):
    """
    Performs speaker diarization on the audio file using a local model.
    
    Args:
        audio_path (str): Path to the audio file
        config_path (str, optional): Path to pyannote configuration file
    
    Returns:
        list: Speaker diarization segments
    """
    global pipeline
    
    print(f"DEBUG: Starting perform_diarization with audio_path={audio_path}, config_path={config_path}")
    
    # Try to load the pipeline if it's not already loaded
    if pipeline is None and config_path:
        print(f"DEBUG: Loading pipeline from config_path={config_path}")
        pipeline = load_pipeline_from_pretrained(config_path)
    elif pipeline is None and os.path.exists(DEFAULT_PYANNOTE_CONFIG_PATH):
        print(f"DEBUG: Loading pipeline from DEFAULT_PYANNOTE_CONFIG_PATH={DEFAULT_PYANNOTE_CONFIG_PATH}")
        pipeline = load_pipeline_from_pretrained(DEFAULT_PYANNOTE_CONFIG_PATH)
    
    # If pipeline is successfully loaded
    if pipeline is not None:
        try:
            print("DEBUG: Pipeline loaded, performing diarization")
            diarization = pipeline(audio_path)
            
            # Extract diarization results into a list
            diarization_output = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                diarization_output.append({
                    "start_time": turn.start,
                    "end_time": turn.end,
                    "speaker": speaker
                })
            
            print(f"DEBUG: Diarization successful, found {len(diarization_output)} segments")
            return diarization_output
        except Exception as e:
            print(f"DEBUG: Error during diarization with pipeline: {str(e)}")
            import traceback
            print(traceback.format_exc())
            # Fall back to basic segmentation without speaker labels
    
    # If pipeline isn't available or diarization failed, 
    # create simple segments without speaker identification
    print("DEBUG: Using fallback method without speaker diarization")
    audio_data, sampling_rate = sf.read(audio_path)
    print(f"DEBUG: Audio loaded for fallback with sampling_rate={sampling_rate}")
    
    # Simple segmentation based on fixed intervals
    try:
        print("DEBUG: Creating simple segments based on fixed intervals")
        # Create segments of 5 seconds each
        segments = []
        segment_length = 5.0  # seconds
        total_duration = len(audio_data) / sampling_rate
        
        for i in range(0, int(total_duration), int(segment_length)):
            end_time = min(i + segment_length, total_duration)
            segments.append({
                "start_time": i,
                "end_time": end_time,
                "speaker": "Speaker"
            })
        
        print(f"DEBUG: Created {len(segments)} segments in fallback mode")
        return segments
    except Exception as e:
        print(f"DEBUG: Error in fallback segmentation: {str(e)}")
        import traceback
        print(traceback.format_exc())
        
        # Ultimate fallback - treat the entire audio as one segment
        print("DEBUG: Using ultimate fallback - one segment for entire audio")
        total_duration = len(audio_data) / sampling_rate
        return [{
            "start_time": 0.0,
            "end_time": total_duration,
            "speaker": "Speaker"
        }]

def match_diarization_to_transcription(transcription_output, diarization_output):
    """
    Assigns speaker labels to transcribed segments using diarization timestamps.
    """
    print(f"DEBUG: Starting match_diarization_to_transcription")
    
    speaker_transcriptions = []

    # Ensure diarization is sorted by start_time
    diarization_output.sort(key=lambda x: x["start_time"])
    print("DEBUG: Sorted diarization segments")

    try:
        for transcript in transcription_output:
            print(f"DEBUG: Processing transcript")
            
            if "offsets" not in transcript:
                print(f"DEBUG: Warning - 'offsets' key not found in transcript")
                continue
                
            for segment in transcript["offsets"]:
                if "text" not in segment or "timestamp" not in segment:
                    print(f"DEBUG: Warning - Required keys missing in segment")
                    continue
                    
                trans_text = segment["text"]
                trans_start = segment["timestamp"][0]
                trans_end = segment["timestamp"][1]

                assigned_speaker = "Unknown"
                max_overlap = 0  # Track best match

                for diarization in diarization_output:
                    dia_start = diarization["start_time"]
                    dia_end = diarization["end_time"]
                    speaker = diarization["speaker"]

                    # Calculate overlap between transcription and diarization segments
                    overlap_start = max(trans_start, dia_start)
                    overlap_end = min(trans_end, dia_end)
                    overlap_duration = max(0, overlap_end - overlap_start)

                    if overlap_duration > max_overlap:
                        assigned_speaker = speaker
                        max_overlap = overlap_duration
                        print(f"DEBUG: Found match: {assigned_speaker} with overlap {overlap_duration:.2f}s for segment {trans_start:.2f}s - {trans_end:.2f}s")

                # Store final transcript with assigned speaker
                speaker_transcriptions.append({
                    "speaker": assigned_speaker,
                    "start_time": trans_start,
                    "end_time": trans_end,
                    "text": trans_text
                })
                
        print(f"DEBUG: Created {len(speaker_transcriptions)} matched segments")
        return speaker_transcriptions
    except Exception as e:
        print(f"DEBUG: Error in match_diarization_to_transcription: {str(e)}")
        import traceback
        print(traceback.format_exc())
        
        # Return empty list on failure
        return []

def format_srt(speaker_transcriptions):
    """
    Converts the speaker-transcribed segments into an SRT format.
    """
    print("DEBUG: Starting format_srt")
    srt_output = []
    
    for idx, segment in enumerate(speaker_transcriptions, start=1):
        start_time = format_timestamp(segment["start_time"])
        end_time = format_timestamp(segment["end_time"])
        text = f"{segment['speaker']}: {segment['text']}"
        
        srt_output.append(f"{idx}\n{start_time} --> {end_time}\n{text}\n")

    print(f"DEBUG: Created SRT with {len(srt_output)} entries")
    return "\n".join(srt_output)

def format_timestamp(seconds):
    """Converts seconds to SRT timestamp format."""
    ms = int((seconds - int(seconds)) * 1000)
    hours, minutes, seconds = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"

def process_audio_sync(audio_path, config_path=None):
    """
    Synchronous version of the audio processing function.
    
    Args:
        audio_path (str): Path to the audio file
        config_path (str, optional): Path to pyannote configuration file
    """
    try:
        print(f"DEBUG: Starting process_audio_sync with audio_path={audio_path}, config_path={config_path}")
        
        # Read audio file
        print("DEBUG: Reading audio file")
        audio_data, sampling_rate = sf.read(audio_path)
        print(f"DEBUG: Audio loaded with sampling_rate={sampling_rate}, shape={audio_data.shape}, duration={len(audio_data)/sampling_rate:.2f}s")
        
        # Transcribe audio with chunking support
        print("DEBUG: Transcribing audio with chunking support")
        transcription_with_timestamps = transcribe_audio_with_timestamps(audio_data, sampling_rate)
        
        # Perform diarization with local model config
        print(f"DEBUG: Performing diarization")
        diarization_output = perform_diarization(audio_path, config_path=config_path)
        
        # Match transcription with speakers
        print("DEBUG: Matching transcription with speakers")
        matched_transcription = match_diarization_to_transcription(transcription_with_timestamps, diarization_output)
        
        # Format as SRT
        print("DEBUG: Formatting as SRT")
        srt_content = format_srt(matched_transcription)
        
        print("DEBUG: process_audio_sync completed successfully")
        return {
            "segments": matched_transcription,
            "srt_content": srt_content
        }
    except Exception as e:
        import traceback
        print(f"DEBUG: Error in process_audio_sync: {str(e)}")
        print(traceback.format_exc())
        raise

async def process_audio(audio_path, config_path=None):
    """
    Asynchronous wrapper for audio processing to not block the web server.
    Note: We're not using ProcessPoolExecutor due to pickling issues.
    
    Args:
        audio_path (str): Path to the audio file
        config_path (str, optional): Path to pyannote configuration file
    """
    print(f"DEBUG: Starting process_audio with audio_path={audio_path}, config_path={config_path}")
    
    # Simply call the sync function directly to avoid pickling issues
    return process_audio_sync(audio_path, config_path)

def transcribe_audio_file(audio_path):
    """
    Simple function to just transcribe audio for testing.
    """
    audio_data, sampling_rate = sf.read(audio_path)
    return transcribe_audio_with_timestamps(audio_data, sampling_rate)