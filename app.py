from fastapi import FastAPI, Request, Depends, Form, File, UploadFile, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import Dict, List, Optional
import os
import uuid
import shutil
from datetime import datetime

# Import project modules
from database import (
    verify_user, get_user, get_user_audio_files, get_audio_file, 
    add_audio_file, update_audio_file_status, get_queue_position,
    get_transcription, get_transcription_by_audio_file, update_transcription,
    submit_for_approval, get_pending_approvals, approve_transcription, 
    reject_transcription, get_flight_commanders_for_unit, 
    get_commanding_officers_for_unit
)
from auth import (
    authenticate_user, create_session, delete_session, 
    pilot_required, flt_cdr_required, co_required
)
from queue_manager import start_queue, stop_queue

# Initialize FastAPI app
app = FastAPI(title="VANI - Audio Transcription System")

# Directory setup
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Setup static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Start the transcription queue processor
@app.on_event("startup")
async def startup_event():
    start_queue()

# Stop the transcription queue processor when the app shuts down
@app.on_event("shutdown")
async def shutdown_event():
    stop_queue()

# Authentication routes
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(
    request: Request, 
    service_no: str = Form(...), 
    password: str = Form(...)
):
    user = verify_user(service_no, password)
    if user:
        # Create session and set cookie
        session_token = create_session(user)
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="session", value=session_token, httponly=True)
        return response
    
    # Authentication failed
    return templates.TemplateResponse(
        "login.html", 
        {"request": request, "error": "Invalid service number or password"}
    )

@app.get("/logout")
async def logout(request: Request):
    # Clear session
    token = request.cookies.get("session")
    if token:
        delete_session(token)
    
    # Redirect to login page
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="session")
    return response

# Dashboard routes
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: Dict = Depends(authenticate_user)):
    audio_files = get_user_audio_files(user["serviceNo"])
    
    # Get pending approvals if user is a commander or officer
    pending_approvals = []
    if user.get("isFltCdr"):
        pending_approvals = get_pending_approvals(user["serviceNo"], "fltcdr")
    elif user.get("isCO"):
        pending_approvals = get_pending_approvals(user["serviceNo"], "co")
    
    return templates.TemplateResponse(
        "dashboard.html", 
        {
            "request": request, 
            "user": user, 
            "audio_files": audio_files,
            "pending_approvals": pending_approvals
        }
    )

# File upload routes
@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, user: Dict = Depends(pilot_required)):
    return templates.TemplateResponse("upload.html", {"request": request, "user": user})

@app.post("/upload")
async def upload_audio(
    request: Request, 
    user: Dict = Depends(pilot_required),
    audio_file: UploadFile = File(...)
):
    # Check file extension
    filename = audio_file.filename
    file_ext = os.path.splitext(filename)[1].lower()
    
    if file_ext not in [".wav", ".mp3", ".flac", ".ogg"]:
        return templates.TemplateResponse(
            "upload.html", 
            {
                "request": request,
                "user": user,
                "error": "Invalid file format. Please upload WAV, MP3, FLAC, or OGG files."
            }
        )
    
    # Create a unique filename
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    # Save the uploaded file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)
    
    # Add file to database
    file_id = add_audio_file(unique_filename, filename, user["serviceNo"])
    
    # Redirect to dashboard
    return RedirectResponse(
        url="/dashboard", 
        status_code=status.HTTP_303_SEE_OTHER,
    )

# Transcription routes
@app.get("/transcription/{file_id}", response_class=HTMLResponse)
async def view_transcription(
    request: Request, 
    file_id: int, 
    user: Dict = Depends(authenticate_user)
):
    # Get audio file data
    audio_file = get_audio_file(file_id)
    
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Check if user has permission to view this file
    if audio_file["uploadedBy"] != user["serviceNo"] and not user.get("isFltCdr") and not user.get("isCO"):
        raise HTTPException(status_code=403, detail="You don't have permission to view this file")
    
    # Get transcription data
    transcription = get_transcription_by_audio_file(file_id)
    
    if not transcription and audio_file["status"] == "queued":
        # File is still in queue
        queue_position = get_queue_position(file_id)
        return templates.TemplateResponse(
            "transcription_queued.html", 
            {
                "request": request, 
                "user": user, 
                "audio_file": audio_file,
                "queue_position": queue_position
            }
        )
    
    if not transcription and audio_file["status"] == "processing":
        # File is currently being processed
        return templates.TemplateResponse(
            "transcription_processing.html", 
            {
                "request": request, 
                "user": user, 
                "audio_file": audio_file
            }
        )
    
    if not transcription:
        # Transcription not found for other reasons
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    # Get available approvers if user is a pilot
    available_flt_cdrs = []
    available_cos = []
    if user.get("isPilot"):
        available_flt_cdrs = get_flight_commanders_for_unit(user["unit"])
        available_cos = get_commanding_officers_for_unit(user["unit"])
    
      # Try to load the brief summary alongside the .srt
    # initialize so it's always defined
    brief_text = None

    # Try to load the brief summary alongside the .srt
    srt_fn = transcription.get("srtFilename")
    print("SRT filename is:", srt_fn)
    if srt_fn:
        base, _ = os.path.splitext(srt_fn)
        brief_name = base + "_brief.txt"
        print("Brief name is:", brief_name)
        brief_path = os.path.join(UPLOAD_DIR, brief_name)
        if os.path.exists(brief_path):
            with open(brief_path, "r", encoding="utf-8") as bf:
                brief_text = bf.read()

    print("Brief text:", brief_text)
    # Return transcription view
    return templates.TemplateResponse(
        "view_transcription.html", 
        {
            "request": request, 
            "user": user, 
            "audio_file": audio_file,
            "transcription": transcription,
            "available_flt_cdrs": available_flt_cdrs,
            "available_cos": available_cos,
            "brief_text": brief_text
        }
    )

@app.get("/edit-transcription/{file_id}", response_class=HTMLResponse)
async def edit_transcription_page(
    request: Request, 
    file_id: int, 
    user: Dict = Depends(pilot_required)
):
    # Get audio file data
    audio_file = get_audio_file(file_id)
    
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Check if user has permission to edit this file
    if audio_file["uploadedBy"] != user["serviceNo"]:
        raise HTTPException(status_code=403, detail="You don't have permission to edit this file")
    
    # Check if file is in editable state
    if audio_file["status"] not in ["transcribed", "rejected"]:
        raise HTTPException(status_code=400, detail="This file cannot be edited in its current state")
    
    # Get transcription data
    transcription = get_transcription_by_audio_file(file_id)
    
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    # Return edit view
    return templates.TemplateResponse(
        "edit_transcription.html", 
        {
            "request": request, 
            "user": user, 
            "audio_file": audio_file,
            "transcription": transcription
        }
    )

@app.post("/update-transcription/{transcription_id}")
async def update_transcription_content(
    request: Request,
    transcription_id: int,
    user: Dict = Depends(pilot_required),
    content: str = Form(...)
):
    # Get transcription data
    transcription = get_transcription(transcription_id)
    
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    # Get audio file data
    audio_file = get_audio_file(transcription["audioFileId"])
    
    # Check if user has permission to edit this transcription
    if audio_file["uploadedBy"] != user["serviceNo"]:
        raise HTTPException(status_code=403, detail="You don't have permission to edit this transcription")
    
    # Check if file is in editable state
    if audio_file["status"] not in ["transcribed", "rejected"]:
        raise HTTPException(status_code=400, detail="This transcription cannot be edited in its current state")
    
    # Update transcription
    success = update_transcription(transcription_id, content, user["serviceNo"])
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update transcription")
    
    # Redirect to transcription view
    return RedirectResponse(
        url=f"/transcription/{audio_file['id']}", 
        status_code=status.HTTP_303_SEE_OTHER
    )

@app.post("/submit-for-approval/{file_id}")
async def submit_transcription_for_approval(
    request: Request,
    file_id: int,
    user: Dict = Depends(pilot_required),
    approver_service_no: str = Form(...),
    level: str = Form(...)
):
    # Get audio file data
    audio_file = get_audio_file(file_id)
    
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Check if user has permission to submit this file
    if audio_file["uploadedBy"] != user["serviceNo"]:
        raise HTTPException(status_code=403, detail="You don't have permission to submit this file")
    
    # Check if file is in submittable state
    if audio_file["status"] not in ["transcribed", "rejected"]:
        raise HTTPException(status_code=400, detail="This file cannot be submitted in its current state")
    
    # Check if level is valid
    if level not in ["fltcdr", "co"]:
        raise HTTPException(status_code=400, detail="Invalid approval level")
    
    # Check if approver exists and has the right role
    approver = get_user(approver_service_no)
    if not approver:
        raise HTTPException(status_code=404, detail="Approver not found")
    
    if level == "fltcdr" and not approver.get("isFltCdr"):
        raise HTTPException(status_code=400, detail="Selected user is not a Flight Commander")
    
    if level == "co" and not approver.get("isCO"):
        raise HTTPException(status_code=400, detail="Selected user is not a Commanding Officer")
    
    # Submit for approval
    approval_id = submit_for_approval(file_id, level, approver_service_no)
    
    # Redirect to dashboard
    return RedirectResponse(
        url="/dashboard", 
        status_code=status.HTTP_303_SEE_OTHER
    )

# Approval routes
# @app.get("/approval/{file_id}", response_class=HTMLResponse)
# async def approval_page(
#     request: Request,
#     file_id: int,
#     user: Dict = Depends(authenticate_user)
# ):
#     # Get audio file data
#     audio_file = get_audio_file(file_id)
    
#     if not audio_file:
#         raise HTTPException(status_code=404, detail="Audio file not found")
    
#     # Check permissions based on file status
#     if audio_file["status"] == "submitted_fltcdr" and not user.get("isFltCdr"):
#         raise HTTPException(status_code=403, detail="Only Flight Commanders can approve this file")
    
#     if audio_file["status"] == "submitted_co" and not user.get("isCO"):
#         raise HTTPException(status_code=403, detail="Only Commanding Officers can approve this file")
    
#     # Get transcription data
#     transcription = get_transcription_by_audio_file(file_id)
    
#     if not transcription:
#         raise HTTPException(status_code=404, detail="Transcription not found")
    
#     # Get uploader info
#     uploader = get_user(audio_file["uploadedBy"])
    
#     return templates.TemplateResponse(
#         "approval.html", 
#         {
#             "request": request, 
#             "user": user, 
#             "audio_file": audio_file,
#             "transcription": transcription,
#             "uploader": uploader
#         }
#     )

@app.get("/approval/{file_id}", response_class=HTMLResponse)
async def approval_page(
    request: Request,
    file_id: int,
    user: Dict = Depends(authenticate_user)
):
    # Get audio file data
    audio_file = get_audio_file(file_id)
    
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Check permissions based on file status
    if audio_file["status"] == "submitted_fltcdr" and not user.get("isFltCdr"):
        raise HTTPException(status_code=403, detail="Only Flight Commanders can approve this file")
    
    if audio_file["status"] == "submitted_co" and not user.get("isCO"):
        raise HTTPException(status_code=403, detail="Only Commanding Officers can approve this file")
    
    # Get transcription data
    transcription = get_transcription_by_audio_file(file_id)
    
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription not found")
    
    # Get uploader info
    uploader = get_user(audio_file["uploadedBy"])
    
    # Get available COs for this unit if user is a Flight Commander
    available_cos = []
    if user.get("isFltCdr"):
        available_cos = get_commanding_officers_for_unit(user["unit"])
    
    return templates.TemplateResponse(
        "approval.html", 
        {
            "request": request, 
            "user": user, 
            "audio_file": audio_file,
            "transcription": transcription,
            "uploader": uploader,
            "available_cos": available_cos
        }
    )
    
# @app.post("/approve/{file_id}")
# async def approve(
#     request: Request,
#     file_id: int,
#     user: Dict = Depends(authenticate_user),
#     comments: str = Form("", min_length=0)
# ):
#     # Get audio file data
#     audio_file = get_audio_file(file_id)
    
#     if not audio_file:
#         raise HTTPException(status_code=404, detail="Audio file not found")
    
#     # Determine approval level and check permissions
#     level = None
#     if audio_file["status"] == "submitted_fltcdr":
#         if not user.get("isFltCdr"):
#             raise HTTPException(status_code=403, detail="Only Flight Commanders can approve this file")
#         level = "fltcdr"
#     elif audio_file["status"] == "submitted_co":
#         if not user.get("isCO"):
#             raise HTTPException(status_code=403, detail="Only Commanding Officers can approve this file")
#         level = "co"
#     else:
#         raise HTTPException(status_code=400, detail="This file is not awaiting approval")
    
#     # Get pending approval record
#     approvals = get_pending_approvals(user["serviceNo"], level)
#     approval_id = None
    
#     for approval in approvals:
#         if approval["audioFileId"] == file_id:
#             approval_id = approval["id"]
#             break
    
#     if not approval_id:
#         raise HTTPException(status_code=404, detail="Approval record not found")
    
#     # Approve the transcription
#     success = approve_transcription(approval_id, comments)
    
#     if not success:
#         raise HTTPException(status_code=500, detail="Failed to approve transcription")
    
#     # Redirect to dashboard
#     return RedirectResponse(
#         url="/dashboard", 
#         status_code=status.HTTP_303_SEE_OTHER
#     )

@app.post("/approve/{file_id}")
async def approve(
    request: Request,
    file_id: int,
    user: Dict = Depends(authenticate_user),
    comments: str = Form("", min_length=0),
    forward_to_co: Optional[str] = Form(None),
    co_service_no: Optional[str] = Form(None)
):
    # Get audio file data
    audio_file = get_audio_file(file_id)
    
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Determine approval level and check permissions
    level = None
    if audio_file["status"] == "submitted_fltcdr":
        if not user.get("isFltCdr"):
            raise HTTPException(status_code=403, detail="Only Flight Commanders can approve this file")
        level = "fltcdr"
    elif audio_file["status"] == "submitted_co":
        if not user.get("isCO"):
            raise HTTPException(status_code=403, detail="Only Commanding Officers can approve this file")
        level = "co"
    else:
        raise HTTPException(status_code=400, detail="This file is not awaiting approval")
    
    # Get pending approval record
    approvals = get_pending_approvals(user["serviceNo"], level)
    approval_id = None
    
    for approval in approvals:
        if approval["audioFileId"] == file_id:
            approval_id = approval["id"]
            break
    
    if not approval_id:
        raise HTTPException(status_code=404, detail="Approval record not found")
    
    # Approve the transcription
    success = approve_transcription(approval_id, comments)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to approve transcription")
    
    # Check if Flight Commander wants to forward to CO
    if level == "fltcdr" and forward_to_co and co_service_no:
        # Verify CO exists
        co_user = get_user(co_service_no)
        if not co_user or not co_user.get("isCO"):
            raise HTTPException(status_code=400, detail="Selected user is not a Commanding Officer")
        
        # Submit for CO approval
        submit_for_approval(file_id, "co", co_service_no)
    
    # Redirect to dashboard
    return RedirectResponse(
        url="/dashboard", 
        status_code=status.HTTP_303_SEE_OTHER
    )

@app.post("/reject/{file_id}")
async def reject(
    request: Request,
    file_id: int,
    user: Dict = Depends(authenticate_user),
    comments: str = Form(..., min_length=1)
):
    # Get audio file data
    audio_file = get_audio_file(file_id)
    
    if not audio_file:
        raise HTTPException(status_code=404, detail="Audio file not found")
    
    # Determine approval level and check permissions
    level = None
    if audio_file["status"] == "submitted_fltcdr":
        if not user.get("isFltCdr"):
            raise HTTPException(status_code=403, detail="Only Flight Commanders can reject this file")
        level = "fltcdr"
    elif audio_file["status"] == "submitted_co":
        if not user.get("isCO"):
            raise HTTPException(status_code=403, detail="Only Commanding Officers can reject this file")
        level = "co"
    else:
        raise HTTPException(status_code=400, detail="This file is not awaiting approval")
    
    # Get pending approval record
    approvals = get_pending_approvals(user["serviceNo"], level)
    approval_id = None
    
    for approval in approvals:
        if approval["audioFileId"] == file_id:
            approval_id = approval["id"]
            break
    
    if not approval_id:
        raise HTTPException(status_code=404, detail="Approval record not found")
    
    # Require comments for rejection
    if not comments:
        raise HTTPException(status_code=400, detail="Comments are required when rejecting a transcription")
    
    # Reject the transcription
    success = reject_transcription(approval_id, comments)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reject transcription")
    
    # Redirect to dashboard
    return RedirectResponse(
        url="/dashboard", 
        status_code=status.HTTP_303_SEE_OTHER
    )

# File download routes
@app.get("/download/{filename}")
async def download_file(filename: str, user: Dict = Depends(authenticate_user)):
    """Endpoint to download generated SRT files."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        path=file_path, 
        media_type="application/octet-stream",
        filename=filename
    )

# Root redirect to login/dashboard
@app.get("/")
async def root(request: Request):
    # Check if user is logged in
    token = request.cookies.get("session")
    if token:
        # Redirect to dashboard
        return RedirectResponse(url="/dashboard")
    
    # Redirect to login
    return RedirectResponse(url="/login")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)