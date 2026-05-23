"""Update the admin base template to add notification link in sidebar."""
import os

content = '''{% extends "base.html" %}

{% block title %}{{ title|default("Admin") }} &mdash; ForgeStore{% endblock %}

{% block body %}
<div class="flex h-full min-h-screen bg-stone-50/50">
    <aside id="sidebar" class="fixed inset-y-0 left-0 z-40 w-64 bg-white border-r border-stone-200 transform -translate-x-full lg:translate-x-0 transition-transform duration-200 lg:relative lg:flex lg:flex-col shadow-lg shadow-stone-900/5">
        <div class="flex items-center gap-3 px-6 h-16 border-b border-stone-100">
            <div class="w-9 h-9 bg-stone-900 rounded-xl flex items-center justify-center shadow-sm">
                <span class="text-white text-sm font-display font-black">FS</span>
            </div>
            <div>
                <span class="text-sm font-display font-black text-stone-900">ForgeStore</span>
                <span class="block text-[10px] font-medium text-stone-400 uppercase tracking-[0.15em]">Admin Panel</span>
            </div>
        </div>
        <div class="px-6 py-4 border-b border-stone-100 bg-gradient-to-r from-stone-50 to-transparent">
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold ring-2 ring-amber-500/20
                    {% if admin.role.value == 'DIR_ADMIN' %}bg-purple-600
                    {% elif admin.role.value == 'MANAGEMENT' %}bg-blue-600
                    {% elif admin.role.value == 'TECH_ADMIN' %}bg-cyan-600
                    {% elif admin.role.value == 'RETAILER' %}bg-amber-600
                    {% else %}bg-emerald-600{% endif %}">
                    {{ admin.name[0]|upper if admin and admin.name else "A" }}
                </div>
                <div>
                    <p class="text-sm font-semibold text-stone-900">{{ admin.name if admin and admin.name else "Admin" }}</p>
                    <p class="text-[11px] text-stone-400">{{ admin.email }}</p>
                    <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider mt-0.5
                        {% if admin.role.value == 'DIR_ADMIN' %}bg-purple-100 text-purple-800
                        {% elif admin.role.value == 'MANAGEMENT' %}bg-blue-100 text-blue-800
                        {% elif admin.role.value == 'TECH_ADMIN' %}bg-cyan-100 text-cyan-800
                        {% elif admin.role.value == 'RETAILER' %}bg-amber-100 text-amber-800
                        {% else %}bg-emerald-100 text-emerald-800{% endif %}">
                        {{ admin.role.value }}
                    </span>
                </div>
            </div>
        </div>
        <nav class="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
            <a href="/admin/dashboard" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>
                Dashboard
            </a>
            <p class="px-3 pt-5 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-stone-400">Inventory</p>
            <a href="/admin/catalog" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>
                Catalog
            </a>
            <a href="/admin/categories" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/></svg>
                Categories
            </a>
            <a href="/admin/retailers" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/></svg>
                Retailers
            </a>
            <p class="px-3 pt-5 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-stone-400">Sales</p>
            <a href="/admin/orders" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/></svg>
                Orders
            </a>
            <a href="/admin/customers" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                Customers
            </a>
            <p class="px-3 pt-5 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-stone-400">System</p>
            <a href="/admin/settings" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                Settings
            </a>
            <p class="px-3 pt-5 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-stone-400">Management</p>
            <a href="/admin/notifications" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group" id="notification-link">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>
                Notifications
                <span id="sidebar-notif-badge" class="ml-auto inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full text-[9px] font-bold bg-amber-500 text-white hidden"></span>
            </a>
            <a href="/admin/admin-users" class="sidebar-link flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 rounded-xl hover:bg-amber-50 hover:text-amber-800 transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-amber-600 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z"/></svg>
                Admin Users
            </a>
        </nav>
        <div class="px-3 py-4 border-t border-stone-100 bg-gradient-to-r from-stone-50 to-transparent">
            <a href="/admin/logout" class="flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-stone-500 hover:bg-red-50 hover:text-red-600 rounded-xl transition-all duration-150 group">
                <svg class="w-5 h-5 text-stone-400 group-hover:text-red-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
                Sign Out
            </a>
        </div>
    </aside>
    <div id="sidebar-backdrop" class="fixed inset-0 bg-black/30 z-30 hidden lg:hidden" onclick="document.getElementById('sidebar').classList.add('-translate-x-full'); this.classList.add('hidden');"></div>
    <div class="flex-1 flex flex-col min-w-0">
        <header class="sticky top-0 z-20 bg-white/80 backdrop-blur-md border-b border-stone-200 lg:hidden">
            <div class="flex items-center justify-between px-4 h-14">
                <button id="sidebar-toggle" class="p-2 -ml-2 text-stone-500 hover:text-stone-900 rounded-lg hover:bg-stone-50 transition-all" onclick="document.getElementById('sidebar').classList.toggle('-translate-x-full'); document.getElementById('sidebar-backdrop').classList.toggle('hidden');">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 6h16M4 12h16M4 18h16"/></svg>
                </button>
                <span class="text-sm font-display font-bold text-stone-900">ForgeStore Admin</span>
                <div class="w-10"></div>
            </div>
        </header>
        <main class="flex-1 p-4 md:p-6 lg:p-8">
            {% block content %}{% endblock %}
        </main>
    </div>
</div>
<script>
async function updateSidebarNotifBadge() {
    try {
        const res = await fetch('/api/admin/notifications/unread-count');
        const data = await res.json();
        const badge = document.getElementById('sidebar-notif-badge');
        if (data.count > 0) {
            badge.textContent = data.count > 99 ? '99+' : data.count;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    } catch (e) {}
}
document.addEventListener('DOMContentLoaded', updateSidebarNotifBadge);
setInterval(updateSidebarNotifBadge, 60000);
</script>
<script src="/static/js/admin.js"></script>
{% endblock %}
'''

filepath = os.path.join(os.path.dirname(__file__), 'app', 'templates', 'admin', 'base.html')
with open(filepath, 'w', newline='') as f:
    f.write(content)
print('Template written successfully to', filepath)
