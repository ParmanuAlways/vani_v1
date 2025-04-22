import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager
import hashlib
import secrets
from typing import Dict, List, Optional, Tuple
import ast  # Add this import for string to list conversion

# Database configuration
DB_NAME = "VANI_DB.sqlite"

def init_db():
    """Initialize the database if it doesn't exist."""
    if not os.path.exists(DB_NAME):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Create Users table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS Users (
                serviceNo TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                password TEXT NOT NULL,
                isPilot INTEGER DEFAULT 0,
                isFltCdr INTEGER DEFAULT 0,
                isCO INTEGER DEFAULT 0
            )
            ''')
            
            # Create AudioFiles table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS AudioFiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                originalFilename TEXT NOT NULL,
                uploadDate TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'queued',
                queuePosition INTEGER,
                uploadedBy TEXT,
                FOREIGN KEY (uploadedBy) REFERENCES Users(serviceNo)
            )
            ''')
            
            # Create Transcriptions table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS Transcriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audioFileId INTEGER NOT NULL,
                transcriptionContent TEXT,
                srtFilename TEXT,
                lastEdited TIMESTAMP,
                editedBy TEXT,
                FOREIGN KEY (audioFileId) REFERENCES AudioFiles(id),
                FOREIGN KEY (editedBy) REFERENCES Users(serviceNo)
            )
            ''')
            
            # Create Approvals table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS Approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audioFileId INTEGER NOT NULL,
                approverServiceNo TEXT NOT NULL,
                approvalLevel TEXT NOT NULL,
                status TEXT NOT NULL,
                comments TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (audioFileId) REFERENCES AudioFiles(id),
                FOREIGN KEY (approverServiceNo) REFERENCES Users(serviceNo)
            )
            ''')
            
            # Add some test users if this is a new database
            add_test_users(cursor)
            
            conn.commit()

def add_test_users(cursor):
    """Add test users with different roles."""
    # Hash passwords
    def hash_password(password):
        salt = secrets.token_hex(8)
        hashed = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        return f"{salt}${hashed}"
    
    users = [
        ('10001', 'John Pilot', 'Alpha Squadron', hash_password('pilot123'), 1, 0, 0),
        ('10002', 'Mike Commander', 'Alpha Squadron', hash_password('fltcdr123'), 0, 1, 0),
        ('10003', 'Sarah Officer', 'Alpha Squadron', hash_password('co123'), 0, 0, 1),
        ('10004', 'David Pilot', 'Beta Squadron', hash_password('pilot456'), 1, 0, 0)
    ]
    
    for user in users:
        cursor.execute('''
        INSERT OR IGNORE INTO Users (serviceNo, name, unit, password, isPilot, isFltCdr, isCO)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', user)

@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# User management functions
def verify_user(service_no: str, password: str) -> Optional[Dict]:
    """Verify user credentials and return user data if valid."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE serviceNo = ?", (service_no,))
        user = cursor.fetchone()
        
        if not user:
            return None
        
        stored_password = user['password']
        salt = stored_password.split('$')[0]
        hashed_input = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        
        if f"{salt}${hashed_input}" == stored_password:
            return dict(user)
        return None

def get_user(service_no: str) -> Optional[Dict]:
    """Get user data by service number."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE serviceNo = ?", (service_no,))
        user = cursor.fetchone()
        return dict(user) if user else None

def get_flight_commanders_for_unit(unit: str) -> List[Dict]:
    """Get all flight commanders for a specific unit."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE unit = ? AND isFltCdr = 1", (unit,))
        return [dict(row) for row in cursor.fetchall()]

def get_commanding_officers_for_unit(unit: str) -> List[Dict]:
    """Get all commanding officers for a specific unit."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE unit = ? AND isCO = 1", (unit,))
        return [dict(row) for row in cursor.fetchall()]

# Audio file management functions
def add_audio_file(filename: str, original_filename: str, uploaded_by: str) -> int:
    """Add a new audio file to the database and return its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get current max queue position
        cursor.execute("SELECT MAX(queuePosition) FROM AudioFiles WHERE status = 'queued'")
        max_queue = cursor.fetchone()[0]
        queue_position = 1 if max_queue is None else max_queue + 1
        
        cursor.execute('''
        INSERT INTO AudioFiles (filename, originalFilename, uploadDate, status, queuePosition, uploadedBy)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (filename, original_filename, datetime.now().isoformat(), 'queued', queue_position, uploaded_by))
        
        file_id = cursor.lastrowid
        conn.commit()
        return file_id

def get_audio_file(file_id: int) -> Optional[Dict]:
    """Get audio file data by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM AudioFiles WHERE id = ?", (file_id,))
        file_data = cursor.fetchone()
        return dict(file_data) if file_data else None

def get_user_audio_files(service_no: str) -> List[Dict]:
    """Get all audio files uploaded by a specific user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT AudioFiles.*, Transcriptions.id as transcription_id,
               Transcriptions.srtFilename as srtFilename
        FROM AudioFiles 
        LEFT JOIN Transcriptions ON AudioFiles.id = Transcriptions.audioFileId
        WHERE uploadedBy = ?
        ORDER BY uploadDate DESC
        ''', (service_no,))
        return [dict(row) for row in cursor.fetchall()]

def update_audio_file_status(file_id: int, status: str) -> bool:
    """Update the status of an audio file."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE AudioFiles SET status = ? WHERE id = ?
        ''', (status, file_id))
        conn.commit()
        return cursor.rowcount > 0

def get_queue_position(file_id: int) -> Optional[int]:
    """Get the queue position of an audio file."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT queuePosition FROM AudioFiles WHERE id = ?", (file_id,))
        result = cursor.fetchone()
        return result['queuePosition'] if result else None

def get_next_audio_file_for_processing() -> Optional[Dict]:
    """Get the next audio file in the queue for processing."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM AudioFiles 
        WHERE status = 'queued' 
        ORDER BY queuePosition ASC 
        LIMIT 1
        ''')
        file_data = cursor.fetchone()
        return dict(file_data) if file_data else None

# Transcription management functions
def add_transcription(audio_file_id: int, transcription_content: str, srt_filename: str, edited_by: str) -> int:
    """Add a new transcription to the database and return its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO Transcriptions (audioFileId, transcriptionContent, srtFilename, lastEdited, editedBy)
        VALUES (?, ?, ?, ?, ?)
        ''', (audio_file_id, transcription_content, srt_filename, datetime.now().isoformat(), edited_by))
        
        transcription_id = cursor.lastrowid
        
        # Update audio file status
        cursor.execute('''
        UPDATE AudioFiles SET status = 'transcribed' WHERE id = ?
        ''', (audio_file_id,))
        
        conn.commit()
        return transcription_id

def get_transcription(transcription_id: int) -> Optional[Dict]:
    """Get transcription data by ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Transcriptions WHERE id = ?", (transcription_id,))
        transcription = cursor.fetchone()
        
        if transcription:
            trans_dict = dict(transcription)
            
            # Parse the transcription content from string to list of dictionaries
            try:
                # Safely evaluate the string representation of the list
                segments = ast.literal_eval(trans_dict['transcriptionContent'])
                trans_dict['segments'] = segments
            except (SyntaxError, ValueError) as e:
                # If parsing fails, create a placeholder
                trans_dict['segments'] = [{"speaker": "Error", "start_time": 0, "end_time": 0, "text": "Error parsing transcription data"}]
            
            return trans_dict
        return None

def get_transcription_by_audio_file(audio_file_id: int) -> Optional[Dict]:
    """Get transcription data by audio file ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Transcriptions WHERE audioFileId = ?", (audio_file_id,))
        transcription = cursor.fetchone()
        
        if transcription:
            trans_dict = dict(transcription)
            
            # Parse the transcription content from string to list of dictionaries
            try:
                # Safely evaluate the string representation of the list
                segments = ast.literal_eval(trans_dict['transcriptionContent'])
                trans_dict['segments'] = segments
            except (SyntaxError, ValueError) as e:
                # If parsing fails, create a placeholder
                trans_dict['segments'] = [{"speaker": "Error", "start_time": 0, "end_time": 0, "text": "Error parsing transcription data"}]
            
            return trans_dict
        return None

def update_transcription(transcription_id: int, content: str, edited_by: str) -> bool:
    """Update transcription content."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE Transcriptions 
        SET transcriptionContent = ?, lastEdited = ?, editedBy = ?
        WHERE id = ?
        ''', (content, datetime.now().isoformat(), edited_by, transcription_id))
        conn.commit()
        return cursor.rowcount > 0

# Approval management functions
def submit_for_approval(audio_file_id: int, level: str, approver_service_no: str) -> int:
    """Submit a transcription for approval."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Update audio file status based on approval level
        new_status = f"submitted_{level}"
        cursor.execute('''
        UPDATE AudioFiles SET status = ? WHERE id = ?
        ''', (new_status, audio_file_id))
        
        # Add approval record
        cursor.execute('''
        INSERT INTO Approvals (audioFileId, approverServiceNo, approvalLevel, status)
        VALUES (?, ?, ?, ?)
        ''', (audio_file_id, approver_service_no, level, 'pending'))
        
        approval_id = cursor.lastrowid
        conn.commit()
        return approval_id

def get_pending_approvals(service_no: str, level: str) -> List[Dict]:
    """Get all pending approvals for a specific approver and level."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT Approvals.*, AudioFiles.originalFilename, Users.name as uploaderName
        FROM Approvals 
        JOIN AudioFiles ON Approvals.audioFileId = AudioFiles.id
        JOIN Users ON AudioFiles.uploadedBy = Users.serviceNo
        WHERE Approvals.approverServiceNo = ? 
        AND Approvals.approvalLevel = ? 
        AND Approvals.status = 'pending'
        ''', (service_no, level))
        return [dict(row) for row in cursor.fetchall()]

def approve_transcription(approval_id: int, comments: str = "") -> bool:
    """Approve a transcription."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get approval info
        cursor.execute("SELECT * FROM Approvals WHERE id = ?", (approval_id,))
        approval = cursor.fetchone()
        
        if not approval:
            return False
        
        # Update approval status
        cursor.execute('''
        UPDATE Approvals 
        SET status = 'approved', comments = ?, timestamp = ?
        WHERE id = ?
        ''', (comments, datetime.now().isoformat(), approval_id))
        
        # Update audio file status
        new_status = f"approved_{approval['approvalLevel']}"
        cursor.execute('''
        UPDATE AudioFiles SET status = ? WHERE id = ?
        ''', (new_status, approval['audioFileId']))
        
        conn.commit()
        return True

def reject_transcription(approval_id: int, comments: str) -> bool:
    """Reject a transcription."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get approval info
        cursor.execute(
            "SELECT * FROM Approvals WHERE id = ?",
             (approval_id,)
             )
        approval = cursor.fetchone()
        
        if not approval:
            return False
        
        # Update approval status
        cursor.execute('''
        UPDATE Approvals 
        SET status = 'rejected', comments = ?, timestamp = ?
        WHERE id = ?
        ''', (comments, datetime.now().isoformat(), approval_id))
        
        # Update audio file status
        cursor.execute('''
        UPDATE AudioFiles SET status = 'rejected' WHERE id = ?
        ''', (approval['audioFileId'],))
        
        conn.commit()
        return True

# Initialize the database when this module is imported
init_db()