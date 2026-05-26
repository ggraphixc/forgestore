// Admin Panel - JavaScript

// ---- PRODUCT CRUD ----
function deleteProduct(productId) {
    handleDelete(`/api/admin/products/${productId}`, 'Are you sure you want to delete this product?');
}

// ---- CATEGORY CRUD ----
function deleteCategory(categoryId) {
    handleDelete(`/api/admin/categories/${categoryId}`, 'Are you sure you want to delete this category? Products in this category will be unlinked.');
}

// ---- RETAILER CRUD ----
function deleteRetailer(retailerId) {
    handleDelete(`/api/admin/retailers/${retailerId}`, 'Are you sure you want to delete this retailer? Products will be unlinked.');
}

// ---- SETTINGS ----
function updateSetting(key, value) {
    fetch(`/api/admin/settings/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) showToast('Setting updated', 'success');
        else showToast('Failed to update', 'error');
    })
    .catch(() => showToast('Failed to update setting', 'error'));
}

// Settings form handler
document.addEventListener('DOMContentLoaded', () => {
    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
        settingsForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(settingsForm);
            let allSuccess = true;

            for (const [key, value] of formData.entries()) {
                try {
                    const res = await fetch(`/api/admin/settings/${key}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ value }),
                    });
                    const data = await res.json();
                    if (!data.success) allSuccess = false;
                } catch {
                    allSuccess = false;
                }
            }

            if (allSuccess) {
                showToast('Settings saved', 'success');
            } else {
                showToast('Some settings failed to save', 'error');
            }
        });
    }
});

// ---- SIDEBAR ACTIVE STATE ----
document.addEventListener('DOMContentLoaded', () => {
    // Set active sidebar link
    const currentPath = window.location.pathname;
    document.querySelectorAll('.sidebar-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href && currentPath.startsWith(href)) {
            link.classList.add('bg-amber-50', 'text-amber-800', 'dark:bg-amber-900/20', 'dark:text-amber-400');
            link.classList.remove('text-stone-500', 'hover:bg-amber-50', 'hover:text-amber-800');
            // Show the active dot
            const dot = link.querySelector('.sidebar-active-dot');
            if (dot) {
                dot.classList.remove('opacity-0');
                dot.classList.add('opacity-100');
            }
        }
    });
});

// ---- MOBILE SIDEBAR TOGGLE (handled by inline onclick on the button) ----
// Sidebar toggle, backdrop click, link close, escape key, and swipe gestures
// are managed by the inline script in admin/base.html via:
//   - onclick="toggleSidebar(event)" on #sidebar-toggle
//   - onclick="closeSidebar()" on #sidebar-close
//   - addEventListener in the template's DOMContentLoaded handler
