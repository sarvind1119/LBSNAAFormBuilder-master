/**
 * reupload.js - Client-side logic for the document re-upload page.
 * Handles file selection, drag-and-drop, validation via API, and result display.
 * Globals from template: REUPLOAD_TOKEN, DOC_TYPE, DOC_LABEL
 */

(function () {
    const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
    const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'application/pdf'];
    const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'pdf'];

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[ch]));
    }

    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const uploadPrompt = document.getElementById('uploadPrompt');
    const uploadLoading = document.getElementById('uploadLoading');
    const validationResult = document.getElementById('validationResult');
    const uploadError = document.getElementById('uploadError');
    const mainContent = document.getElementById('mainContent');
    const successScreen = document.getElementById('successScreen');

    // Drag and drop
    ['dragenter', 'dragover'].forEach(evt => {
        dropZone.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('border-primary-400', 'bg-primary-50');
        });
    });

    ['dragleave', 'drop'].forEach(evt => {
        dropZone.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('border-primary-400', 'bg-primary-50');
        });
    });

    dropZone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) handleFile(files[0]);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
        // Reset state
        uploadError.classList.add('hidden');
        validationResult.classList.add('hidden');

        // Validate file type
        const ext = file.name.split('.').pop().toLowerCase();
        if (!ALLOWED_EXTS.includes(ext)) {
            showError('Invalid file type. Please upload JPG, PNG, or PDF.');
            return;
        }

        // Validate file size
        if (file.size > MAX_FILE_SIZE) {
            showError('File size exceeds 5MB limit.');
            return;
        }

        uploadDocument(file);
    }

    async function uploadDocument(file) {
        // Show loading
        uploadPrompt.classList.add('hidden');
        uploadLoading.classList.remove('hidden');
        dropZone.style.pointerEvents = 'none';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch(`/api/reupload/${REUPLOAD_TOKEN}`, {
                method: 'POST',
                body: formData,
            });

            const data = await resp.json();

            if (resp.ok && data.status === 'success') {
                showResult(data.validation, file.name);
            } else {
                showError(data.message || 'Validation failed. Please try again.');
                resetUploadUI();
            }
        } catch (err) {
            showError('Network error. Please check your connection and try again.');
            resetUploadUI();
        }
    }

    function showResult(validation, filename) {
        uploadLoading.classList.add('hidden');

        const isValid = validation.is_valid;
        const resultType = validation.result || '';

        const unreadable = resultType === 'BLANK' || resultType === 'ERROR';
        let bgClass, textClass, icon, title;

        if (isValid) {
            bgClass = 'bg-green-50 border border-green-200';
            textClass = 'text-green-700';
            icon = '<svg class="w-6 h-6 text-green-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
            title = 'Document uploaded';
        } else if (unreadable) {
            bgClass = 'bg-red-50 border border-red-200';
            textClass = 'text-red-700';
            icon = '<svg class="w-6 h-6 text-red-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';
            title = resultType === 'BLANK' ? 'This file looks blank' : "We couldn't read this file";
        } else {
            bgClass = 'bg-amber-50 border border-amber-200';
            textClass = 'text-amber-900';
            icon = '<svg class="w-6 h-6 text-amber-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>';
            title = 'Document uploaded';
        }

        let html = `
            <div class="flex items-start gap-3">
                ${icon}
                <div>
                    <p class="font-semibold ${textClass}">${title}</p>
                    <p class="text-xs text-gray-400 mt-1">File: ${escapeHtml(filename)}</p>
                </div>
            </div>`;

        // Verdict details (confidence, name match, celebrity check) are for the course team only.
        validationResult.className = `mt-4 p-4 rounded-lg ${bgClass}`;
        validationResult.innerHTML = html;
        validationResult.classList.remove('hidden');

        // Show success screen if accepted
        if (isValid) {
            setTimeout(() => {
                mainContent.classList.add('hidden');
                successScreen.classList.remove('hidden');
                document.getElementById('successMessage').textContent =
                    `Your ${DOC_LABEL} has been re-uploaded successfully.`;
            }, 2000);
        } else {
            // The re-upload link is single-use, so explain what happens next.
            const nextStep = unreadable
                ? 'This re-upload link has now been used. Please contact the course team so they can send you a new link.'
                : "Our automatic check couldn't confirm this document, but the check often gets it wrong. If this is the correct document, there is nothing more to do: it has been saved and the course team will review it.";
            validationResult.innerHTML += `
                <p class="text-sm text-gray-600 mt-3 border-t pt-3">${nextStep}</p>`;
        }
    }

    function showError(msg) {
        uploadError.textContent = msg;
        uploadError.classList.remove('hidden');
    }

    function resetUploadUI() {
        uploadLoading.classList.add('hidden');
        uploadPrompt.classList.remove('hidden');
        dropZone.style.pointerEvents = '';
        fileInput.value = '';
    }
})();
