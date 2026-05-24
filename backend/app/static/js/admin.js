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

// ---- SIDEBAR ACTIVE STATE & MOBILE TOGGLE ----
document.addEventListener('DOMContentLoaded', () => {
    // Set active sidebar link
    const currentPath = window.location.pathname;
    document.querySelectorAll('.sidebar-link').forEach(link => {
        const href = link.getAttribute('href');
        if (href && currentPath.startsWith(href)) {
            link.classList.add('bg-zinc-100', 'text-zinc-900');
            link.classList.remove('text-zinc-500', 'hover:bg-zinc-50', 'hover:text-zinc-700');
        }
    });

    // Mobile sidebar toggle
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    const sidebarBackdrop = document.getElementById('sidebar-backdrop');

    if (sidebarToggle && sidebar && sidebarBackdrop) {
        const toggleSidebar = () => {
            const isOpen = !sidebar.classList.contains('-translate-x-full');
            sidebar.classList.toggle('-translate-x-full');
            sidebarBackdrop.classList.toggle('hidden');
            sidebarToggle.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
        };

        sidebarToggle.addEventListener('click', toggleSidebar);

        // Close sidebar when clicking backdrop
        sidebarBackdrop.addEventListener('click', () => {
            sidebar.classList.add('-translate-x-full');
            sidebarBackdrop.classList.add('hidden');
            sidebarToggle.setAttribute('aria-expanded', 'false');
        });

        // Close sidebar when clicking a link
        sidebar.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                sidebar.classList.add('-translate-x-full');
                sidebarBackdrop.classList.add('hidden');
                sidebarToggle.setAttribute('aria-expanded', 'false');
            });
        });

        // Close sidebar with Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !sidebar.classList.contains('-translate-x-full')) {
                toggleSidebar();
            }
        });

        // Touch swipe-left to close sidebar
        let touchStartX = 0;
        let touchStartTime = 0;
        let isDraggingSidebar = false;

        sidebar.addEventListener('touchstart', (e) => {
            if (sidebar.classList.contains('-translate-x-full')) return;
            touchStartX = e.touches[0].clientX;
            touchStartTime = Date.now();
            isDraggingSidebar = true;
            sidebar.style.transition = 'none';
        }, { passive: true });

        sidebar.addEventListener('touchmove', (e) => {
            if (!isDraggingSidebar) return;
            const currentX = e.touches[0].clientX;
            const deltaX = currentX - touchStartX;
            if (deltaX < 0) { // Only translate when dragging left
                sidebar.style.transform = `translateX(${deltaX}px)`;
                if (sidebarBackdrop) {
                    const opacity = Math.max(0, 1 - (Math.abs(deltaX) / 280));
                    sidebarBackdrop.style.opacity = opacity;
                }
            }
        }, { passive: true });

        sidebar.addEventListener('touchend', (e) => {
            if (!isDraggingSidebar) return;
            isDraggingSidebar = false;
            sidebar.style.transition = '';
            sidebar.style.transform = '';
            if (sidebarBackdrop) {
                sidebarBackdrop.style.opacity = '';
            }

            const endX = e.changedTouches[0].clientX;
            const deltaX = endX - touchStartX;
            const elapsed = Date.now() - touchStartTime;
            const velocity = Math.abs(deltaX) / elapsed;

            if (deltaX < -80 || (velocity > 0.5 && deltaX < -20)) {
                sidebar.classList.add('-translate-x-full');
                sidebarBackdrop.classList.add('hidden');
                sidebarToggle.setAttribute('aria-expanded', 'false');
            }
        }, { passive: true });
    }
});
