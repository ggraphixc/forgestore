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

// Confirm Dialog
function confirmAction(message) {
    return new Promise((resolve) => {
        const confirmed = window.confirm(message);
        resolve(confirmed);
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
        const res = await fetch(url, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            showToast('Deleted successfully', 'success');
            // Reload the page to reflect changes
            setTimeout(() => window.location.reload(), 500);
        } else {
            showToast(data.error || 'Failed to delete', 'error');
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

    // Mobile sidebar toggle (admin)
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener('click', () => {
            sidebar.classList.toggle('-translate-x-full');
            document.getElementById('sidebar-backdrop')?.classList.toggle('hidden');
        });
    }

    // Web mobile menu toggle
    const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
    const mobileMenu = document.getElementById('mobile-menu');
    const mobileBackdrop = document.getElementById('mobile-backdrop');
    const menuIconOpen = document.getElementById('menu-icon-open');
    const menuIconClose = document.getElementById('menu-icon-close');

    if (mobileMenuToggle && mobileMenu && mobileBackdrop) {
        const toggleMenu = () => {
            const isOpen = !mobileMenu.classList.contains('hidden');
            mobileMenu.classList.toggle('hidden');
            mobileBackdrop.classList.toggle('hidden');
            mobileBackdrop.classList.toggle('opacity-0');
            mobileBackdrop.classList.toggle('pointer-events-none');
            menuIconOpen?.classList.toggle('hidden');
            menuIconClose?.classList.toggle('hidden');
            mobileMenuToggle.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
        };

        mobileMenuToggle.addEventListener('click', toggleMenu);

        // Close menu when clicking backdrop
        mobileBackdrop.addEventListener('click', toggleMenu);

        // Close menu when clicking menu links
        mobileMenu.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', toggleMenu);
        });

        // Close menu with Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !mobileMenu.classList.contains('hidden')) {
                toggleMenu();
            }
        });
    }
});
