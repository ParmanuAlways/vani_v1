document.addEventListener('DOMContentLoaded', function() {
    // File upload handling
    const fileInput = document.getElementById('audio-file');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            if (this.files && this.files[0]) {
                const fileName = this.files[0].name;
                const fileSize = (this.files[0].size / (1024 * 1024)).toFixed(2);
                
                // Update file input label with selected file info
                const fileInfoElem = document.createElement('div');
                fileInfoElem.className = 'selected-file-info';
                fileInfoElem.innerHTML = `Selected: <strong>${fileName}</strong> (${fileSize} MB)`;
                
                // Remove previous info if exists
                const prevInfo = document.querySelector('.selected-file-info');
                if (prevInfo) {
                    prevInfo.remove();
                }
                
                // Add new info
                fileInput.parentElement.appendChild(fileInfoElem);
            }
        });
    }
    
    // Handle approval level selection in submission form
    const approvalLevelSelect = document.getElementById('approval-level');
    if (approvalLevelSelect) {
        const fltcdrGroup = document.getElementById('fltcdr-select-group');
        const coGroup = document.getElementById('co-select-group');
        const fltcdrSelect = document.getElementById('fltcdr-select');
        const coSelect = document.getElementById('co-select');
        
        approvalLevelSelect.addEventListener('change', function() {
            if (this.value === 'fltcdr') {
                fltcdrGroup.style.display = 'block';
                coGroup.style.display = 'none';
                fltcdrSelect.disabled = false;
                coSelect.disabled = true;
            } else {
                fltcdrGroup.style.display = 'none';
                coGroup.style.display = 'block';
                fltcdrSelect.disabled = true;
                coSelect.disabled = false;
            }
        });
    }
    
    // Show loading spinner during form submission
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitButton = this.querySelector('button[type="submit"]');
            if (submitButton) {
                const originalText = submitButton.innerHTML;
                submitButton.disabled = true;
                submitButton.innerHTML = `<span>Processing...</span> <div class="spinner"></div>`;
                
                // Add spinner styling if not already in CSS
                if (!document.getElementById('spinner-style')) {
                    const style = document.createElement('style');
                    style.id = 'spinner-style';
                    style.textContent = `
                        .spinner {
                            display: inline-block;
                            width: 16px;
                            height: 16px;
                            border: 3px solid rgba(255,255,255,.3);
                            border-radius: 50%;
                            border-top-color: white;
                            animation: spin 1s ease-in-out infinite;
                            vertical-align: middle;
                            margin-left: 8px;
                        }
                        
                        @keyframes spin {
                            to { transform: rotate(360deg); }
                        }
                    `;
                    document.head.appendChild(style);
                }
                
                // Reset button state if form submission fails
                setTimeout(() => {
                    if (!form.classList.contains('submitted')) {
                        submitButton.disabled = false;
                        submitButton.innerHTML = originalText;
                    }
                }, 10000); // 10 second timeout
            }
            
            form.classList.add('submitted');
        });
    });
    
    // Automatically refresh status page for queued/processing files
    const isStatusPage = document.querySelector('.queue-status, .processing-status');
    if (isStatusPage) {
        // Refresh every 30 seconds
        setTimeout(() => {
            window.location.reload();
        }, 30000);
    }
    
    // Handle segment highlighting in transcription view
    const segments = document.querySelectorAll('.segment');
    if (segments.length > 0) {
        segments.forEach(segment => {
            segment.addEventListener('click', function() {
                // Remove highlight from all segments
                segments.forEach(s => s.classList.remove('highlight'));
                
                // Add highlight to clicked segment
                this.classList.add('highlight');
            });
        });
        
        // Add highlight style
        const style = document.createElement('style');
        style.textContent = `
            .segment.highlight {
                box-shadow: 0 0 0 2px var(--accent-color);
            }
        `;
        document.head.appendChild(style);
    }
});