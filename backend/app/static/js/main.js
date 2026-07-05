// ForgeStore - Main JavaScript

// Toast Notification System
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-6 right-6 px-6 py-3 rounded-xl text-white text-sm font-medium shadow-2xl z-50 transform transition-all duration-300 translate-y-0 opacity-0 ${
        type === 'success' ? 'bg-emerald-600' : type === 'error' ? 'bg-red-600' : 'bg-zinc-800'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);

    requestAnimationFrame(() => {
        toast.style.opacity = '1';
    });

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Confirm Dialog — Custom Modal (cross-browser, no window.confirm)
function confirmAction(message) {
    return new Promise((resolve) => {
        // Remove any existing modal
        const existing = document.getElementById('fs-confirm-modal');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'fs-confirm-modal';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);backdrop-filter:blur(4px);z-index:9999;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity 0.2s;';

        overlay.innerHTML = `
        <div style="background:#fff;border-radius:16px;padding:28px 32px;max-width:400px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.2);text-align:center;transform:scale(0.95);transition:transform 0.2s;">
            <div style="width:48px;height:48px;border-radius:50%;background:#fef3c7;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
                <svg width="24" height="24" fill="none" stroke="#d97706" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
            </div>
            <p style="font-size:15px;font-weight:600;color:#1c1917;margin:0 0 20px;line-height:1.5;">${message}</p>
            <div style="display:flex;gap:12px;justify-content:center;">
                <button id="fs-confirm-cancel" style="padding:10px 24px;border-radius:10px;border:1px solid #e7e5e4;background:#fff;color:#57534e;font-size:14px;font-weight:600;cursor:pointer;min-height:44px;transition:all 0.15s;">Cancel</button>
                <button id="fs-confirm-ok" style="padding:10px 24px;border-radius:10px;border:none;background:#1c1917;color:#fff;font-size:14px;font-weight:600;cursor:pointer;min-height:44px;transition:all 0.15s;">Confirm</button>
            </div>
        </div>`;

        document.body.appendChild(overlay);
        requestAnimationFrame(() => { overlay.style.opacity = '1'; overlay.querySelector('div').style.transform = 'scale(1)'; });

        const cleanup = (result) => {
            overlay.style.opacity = '0';
            overlay.querySelector('div').style.transform = 'scale(0.95)';
            setTimeout(() => { overlay.remove(); resolve(result); }, 200);
        };

        document.getElementById('fs-confirm-ok').onclick = () => cleanup(true);
        document.getElementById('fs-confirm-cancel').onclick = () => cleanup(false);
        overlay.onclick = (e) => { if (e.target === overlay) cleanup(false); };
        document.addEventListener('keydown', function onKey(e) {
            if (e.key === 'Escape') { document.removeEventListener('keydown', onKey); cleanup(false); }
        });
    });
}

// Format price with currency symbol
function formatPrice(amount, currency = 'NGN') {
    const symbols = { NGN: '₦', USD: '$', GBP: '£', EUR: '€' };
    const symbol = symbols[currency] || '₦';
    return symbol + parseFloat(amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Delete confirmation handler
async function handleDelete(url, message = 'Are you sure? This action cannot be undone.') {
    if (!await confirmAction(message)) return;

    try {
        const res = await fetch(url, { method: 'DELETE', credentials: 'include' });
        const text = await res.text();
        let data;
        try { data = JSON.parse(text); } catch(e) { data = { success: false, error: text || 'Server error' }; }
        const errMsg = data.detail || data.error || (res.ok ? null : 'Failed to delete');
        if (data.success) {
            showToast('Deleted successfully', 'success');
            setTimeout(() => window.location.reload(), 500);
        } else {
            showToast(errMsg || 'Failed to delete', 'error');
        }
    } catch (err) {
        showToast('Failed to delete. Please try again.', 'error');
        console.error('Delete error:', err);
    }
}

// Form submission handler for API forms
function setupApiForm(formId, apiUrl, successMessage = 'Saved successfully', redirectUrl = null) {
    const form = document.getElementById(formId);
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = form.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<svg class="animate-spin w-4 h-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Saving...';

        try {
            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());

            const res = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });

            const result = await res.json();
            if (result.success) {
                showToast(successMessage, 'success');
                if (redirectUrl) {
                    setTimeout(() => window.location.href = redirectUrl, 500);
                }
            } else {
                showToast(result.error || 'Failed to save', 'error');
            }
        } catch (err) {
            showToast('An error occurred. Please try again.', 'error');
            console.error('Form error:', err);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save';
        }
    });
}

// Image Upload Handler
function setupImageUpload(inputId, previewId, apiUrl = '/api/admin/upload') {
    const input = document.getElementById(inputId);
    const preview = document.getElementById(previewId);
    if (!input || !preview) return;

    input.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);
        if (files.length === 0) return;

        const formData = new FormData();
        files.forEach(file => formData.append('files', file));

        try {
            const res = await fetch(apiUrl, {
                method: 'POST',
                body: formData,
            });
            const data = await res.json();
            if (data.urls) {
                data.urls.forEach(url => {
                    const img = document.createElement('img');
                    img.src = url;
                    img.className = 'w-24 h-24 object-cover rounded-lg border border-zinc-200';
                    preview.appendChild(img);
                });
                // Also store in hidden input
                const hiddenInput = document.getElementById('images-input');
                if (hiddenInput) {
                    const existing = hiddenInput.value ? JSON.parse(hiddenInput.value) : [];
                    existing.push(...data.urls);
                    hiddenInput.value = JSON.stringify(existing);
                }
            }
        } catch (err) {
            showToast('Upload failed', 'error');
            console.error('Upload error:', err);
        }
        e.target.value = '';
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Auto-dismiss alerts
    document.querySelectorAll('.alert-auto-dismiss').forEach(el => {
        setTimeout(() => {
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 300);
        }, 4000);
    });

    // Mobile sidebar toggle is handled by inline onclick in admin/base.html
});
