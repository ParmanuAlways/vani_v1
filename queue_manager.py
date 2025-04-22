import threading
import time
import os
from typing import Dict, Optional
import logging
from database import (
    get_next_audio_file_for_processing, 
    update_audio_file_status, 
    add_transcription,
    get_user
)
from transcription_utils import process_audio_sync

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('transcription_queue.log')
    ]
)
logger = logging.getLogger('queue_manager')

# Global variables
UPLOAD_DIR = "uploads"
MODELS_DIR = "models"
DEFAULT_PYANNOTE_CONFIG_PATH = os.path.join(MODELS_DIR, "pyannote_diarization_config.yaml")
QUEUE_RUNNING = False
QUEUE_THREAD = None

def process_queue():
    """
    Process the transcription queue in a loop.
    This function runs in a separate thread.
    """
    global QUEUE_RUNNING
    
    logger.info("Starting transcription queue processor")
    
    while QUEUE_RUNNING:
        try:
            # Get the next file to process
            audio_file = get_next_audio_file_for_processing()
            
            if audio_file:
                file_id = audio_file['id']
                filename = audio_file['filename']
                file_path = os.path.join(UPLOAD_DIR, filename)
                uploaded_by = audio_file['uploadedBy']

                logger.info(f"Processing file {filename} (ID: {file_id})")
                
                try:
                    # Update status to processing
                    update_audio_file_status(file_id, 'processing')
                    
                    # Use configuration file if it exists
                    config_path = DEFAULT_PYANNOTE_CONFIG_PATH if os.path.exists(DEFAULT_PYANNOTE_CONFIG_PATH) else None
                    
                    # Process the audio file
                    result = process_audio_sync(file_path, config_path=config_path)
                    
                    # Generate SRT file name
                    srt_filename = f"{os.path.splitext(filename)[0]}.srt"
                    srt_path = os.path.join(UPLOAD_DIR, srt_filename)
                    
                    # Write SRT file
                    with open(srt_path, "w") as f:
                        f.write(result["srt_content"])
                    
                    # Store transcription in database
                    transcription_content = str(result["segments"])  # Convert to string for storage
                    add_transcription(file_id, transcription_content, srt_filename, uploaded_by)
                    
                    logger.info(f"Successfully processed file {filename}")
                
                except Exception as e:
                    logger.error(f"Error processing file {filename}: {str(e)}")
                    update_audio_file_status(file_id, 'error')
            
            # Sleep for a bit before checking for the next file
            time.sleep(5)
        
        except Exception as e:
            logger.error(f"Queue processor error: {str(e)}")
            time.sleep(10)  # Longer sleep on error

def start_queue():
    """Start the queue processor in a background thread."""
    global QUEUE_RUNNING, QUEUE_THREAD
    
    if QUEUE_RUNNING:
        logger.warning("Queue processor is already running")
        return
    
    QUEUE_RUNNING = True
    QUEUE_THREAD = threading.Thread(target=process_queue)
    QUEUE_THREAD.daemon = True
    QUEUE_THREAD.start()
    
    logger.info("Queue processor thread started")
    return QUEUE_THREAD

def stop_queue():
    """Stop the queue processor."""
    global QUEUE_RUNNING
    
    if not QUEUE_RUNNING:
        logger.warning("Queue processor is not running")
        return
    
    QUEUE_RUNNING = False
    logger.info("Queue processor stopping (will complete current file)")

# Create required directories
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)