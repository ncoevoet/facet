"""
Person-specific photo page Blueprint for Facet viewer.

Provides a dedicated /person/<int:person_id> page showing all photos
of a specific person with full sorting and filtering capabilities.
"""

from flask import Blueprint, render_template_string, request, jsonify, session
import math
from viewer.config import VIEWER_CONFIG
from viewer.types import SORT_OPTIONS, SORT_OPTIONS_GROUPED, VALID_SORT_COLS
from viewer.db_helpers import (
    get_db_connection, get_existing_columns,
    PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS, split_photo_tags,
    HIDE_BLINKS_SQL, HIDE_BURSTS_SQL, get_visibility_clause
)
from viewer.filters import format_date
from viewer.auth import get_session_user_id

person_bp = Blueprint('person', __name__)


def get_person_info(person_id):
    """Fetch person details including photo count."""
    conn = get_db_connection()
    row = conn.execute("""
        SELECT p.id, p.name, p.representative_face_id,
               COUNT(DISTINCT f.photo_path) as photo_count
        FROM persons p
        LEFT JOIN faces f ON f.person_id = p.id
        WHERE p.id = ?
        GROUP BY p.id
    """, (person_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        'id': row['id'],
        'name': row['name'] or f'Person {row["id"]}',
        'photo_count': row['photo_count'],
        'representative_face_id': row['representative_face_id']
    }


def _query_person_photos(person_id, args):
    """Shared query logic for person_page() and person_api().

    Returns (photos, page, total_pages, total_count, sort_col, sort_label, params).
    """
    # Pagination
    default_per_page = VIEWER_CONFIG['pagination']['default_per_page']
    per_page = args.get('per_page', default_per_page, type=int)
    page = args.get('page', 1, type=int)
    offset = (page - 1) * per_page

    # Build params
    params = {
        'sort': args.get('sort', 'aggregate'),
        'dir': args.get('dir', 'DESC'),
        'hide_blinks': args.get('hide_blinks', ''),
        'hide_bursts': args.get('hide_bursts', ''),
        'date_from': args.get('date_from', ''),
        'date_to': args.get('date_to', ''),
    }

    # Validate sort column
    sort_col = params['sort'] if params['sort'] in VALID_SORT_COLS else 'aggregate'
    sort_dir = 'ASC' if params['dir'] == 'ASC' else 'DESC'

    # Build query with person filter
    where_clauses = ["path IN (SELECT photo_path FROM faces WHERE person_id = ?)"]
    sql_params = [person_id]

    # Multi-user visibility
    user_id = get_session_user_id()
    if user_id:
        vis_sql, vis_params = get_visibility_clause(user_id)
        where_clauses.append(vis_sql)
        sql_params.extend(vis_params)

    if params['hide_blinks'] == '1':
        where_clauses.append(HIDE_BLINKS_SQL)
    if params['hide_bursts'] == '1':
        where_clauses.append(HIDE_BURSTS_SQL)
    if params['date_from']:
        date_from = params['date_from'].replace('-', ':')
        where_clauses.append("date_taken >= ?")
        sql_params.append(date_from)
    if params['date_to']:
        date_to = params['date_to'].replace('-', ':') + " 23:59:59"
        where_clauses.append("date_taken <= ?")
        sql_params.append(date_to)

    where_sql = " AND ".join(where_clauses)

    conn = get_db_connection()
    try:
        total_count = conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {where_sql}", sql_params
        ).fetchone()[0]
        total_pages = max(1, math.ceil(total_count / per_page))

        existing_cols = get_existing_columns(conn)
        select_cols = list(PHOTO_BASE_COLS) + [c for c in PHOTO_OPTIONAL_COLS if c in existing_cols]

        query = f"""
            SELECT {', '.join(select_cols)}
            FROM photos
            WHERE {where_sql}
            ORDER BY {sort_col} {sort_dir}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, sql_params + [per_page, offset]).fetchall()

        tags_limit = VIEWER_CONFIG['display']['tags_per_photo']
        photos = split_photo_tags(rows, tags_limit)
    finally:
        conn.close()

    sort_label = next((label for val, label in SORT_OPTIONS if val == sort_col), 'Score')

    return photos, page, total_pages, total_count, sort_col, sort_label, params


# --- TEMPLATE ---
PERSON_PAGE_TEMPLATE = '''
<!DOCTYPE html>
<html class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ person.name }} - Facet</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'photo-dark': '#0b0b0b',
                        'photo-card': '#151515',
                        'photo-accent': '#4CAF50'
                    }
                }
            }
        }
    </script>
    <style type="text/tailwindcss">
        @layer utilities {
            .filter-input {
                @apply bg-neutral-800 text-white border border-neutral-600 px-3 py-2 rounded-md text-sm focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500 w-full;
            }
        }
    </style>
    <style>
        /* Hover preview styles */
        #hover-preview {
            position: fixed;
            z-index: 100;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.15s ease-out;
            max-width: 480px;
            max-height: 480px;
        }
        #hover-preview.visible {
            opacity: 1;
        }
        #hover-preview img {
            max-width: 480px;
            max-height: 480px;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
            border: 2px solid #404040;
        }
        /* Responsive card sizing */
        @media (min-width: 640px) {
            .photo-card {
                width: var(--card-width) !important;
                max-width: var(--card-width) !important;
            }
            .photo-card img {
                width: {{ viewer_config.display.image_width_px }}px !important;
            }
        }
    </style>
</head>
<body class="bg-neutral-950 text-neutral-200 min-h-screen">
    <!-- Hover Preview -->
    <div id="hover-preview"><img src="" alt="Preview"></div>

    <!-- Person Header -->
    <header class="bg-neutral-900 border-b border-neutral-800 px-4 sm:px-6 py-3 sm:sticky sm:top-0 z-40">
        <form id="filterForm" method="GET" class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-4">
            <!-- Row 1: Person Info -->
            <div class="flex items-center gap-4 w-full sm:w-auto">
                <img src="/person_thumbnail/{{ person.id }}" class="w-10 h-10 sm:w-12 sm:h-12 rounded-full object-cover border-2 border-neutral-700" alt="">
                <div>
                    <h1 class="text-lg sm:text-xl font-bold text-white">{{ person.name }}</h1>
                    <span class="text-neutral-500 text-sm">{{ person.photo_count }} {{ _('ui.labels.photos') }}</span>
                </div>
            </div>

            <!-- Row 2: Date Filters -->
            <div class="flex items-center gap-3 w-full sm:w-auto">
                <div class="flex items-center gap-1.5 flex-1 sm:flex-none">
                    <label class="text-neutral-500 text-sm">{{ _('ui.labels.from') }}:</label>
                    <input type="date" name="date_from" value="{{ params.date_from or '' }}"
                           class="bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none flex-1 sm:flex-none"
                           onchange="this.form.submit()">
                </div>
                <div class="flex items-center gap-1.5 flex-1 sm:flex-none">
                    <label class="text-neutral-500 text-sm">{{ _('ui.labels.to') }}:</label>
                    <input type="date" name="date_to" value="{{ params.date_to or '' }}"
                           class="bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none flex-1 sm:flex-none"
                           onchange="this.form.submit()">
                </div>
            </div>

            <!-- Row 3: Sort Controls -->
            <div class="flex items-center gap-2 w-full sm:w-auto">
                <select name="sort" onchange="this.form.submit()"
                        class="bg-neutral-800 text-white text-sm px-2 py-1.5 rounded border border-neutral-700 focus:border-green-500 focus:outline-none flex-1 sm:flex-none">
                    {% if sort_options_grouped %}
                        {% for category, options in sort_options_grouped.items() %}
                        <optgroup label="{{ category }}">
                            {% for opt in options %}
                            <option value="{{ opt.column }}" {% if params.sort == opt.column %}selected{% endif %}>{{ opt.label }}</option>
                            {% endfor %}
                        </optgroup>
                        {% endfor %}
                    {% endif %}
                </select>
                <button type="button" onclick="toggleSortDir()"
                        class="bg-neutral-800 text-white px-3 py-1.5 rounded border border-neutral-700 hover:border-green-500 text-sm transition-colors"
                        title="Toggle sort direction">
                    {% if params.dir == 'ASC' %}&#8593;{% else %}&#8595;{% endif %}
                </button>
                <input type="hidden" name="dir" id="sortDir" value="{{ params.dir }}">
            </div>
        </form>
    </header>

    <!-- Photo Grid -->
    <div class="px-2 py-3">
        <div id="photo-grid" class="flex flex-wrap justify-center gap-2" data-page="{{ page }}" data-total-pages="{{ total_pages }}" data-sort-col="{{ sort_col }}" data-person-id="{{ person.id }}">
            {% for p in photos %}
            <div class="photo-card bg-neutral-900 flex flex-col gap-1 rounded border border-neutral-800 p-1.5 hover:border-green-500 transition-all w-full sm:w-auto" style="max-width: 100%; --card-width: {{ viewer_config.display.card_width_px }}px">
                <!-- Thumbnail -->
                <div class="flex-initial relative" onclick="toggleSelection(this, '{{ p.filename | js_escape }}', '{{ p.path | js_escape }}')">
                    <img
                        src="/thumbnail?path={{ p.path | urlencode }}&size=640"
                        loading="lazy"
                        data-tooltip="[{{ p.category | default('others') | title }}] Aggregate: {{ p.aggregate | safe_float(1) }}&#10;&#10;── Quality ──&#10;Aesthetic: {{ p.aesthetic | safe_float(1) }}{% if p.quality_score %}&#10;Quality: {{ p.quality_score | safe_float(1) }}{% endif %}{% if p.face_count and p.face_count > 0 %}&#10;Face Quality: {{ p.face_quality | safe_float(1) }}&#10;Face Sharpness: {{ p.face_sharpness | safe_float(1) }}&#10;Eye Sharpness: {{ p.eye_sharpness | safe_float(1) }}{% endif %}&#10;Tech Sharpness: {{ p.tech_sharpness | safe_float(1) }}&#10;&#10;── Composition ──&#10;Composition: {{ p.comp_score | safe_float(1) }}{% if p.composition_pattern %}&#10;Pattern: {{ p.composition_pattern | replace('_', ' ') | title }}{% endif %}{% if p.power_point_score %}&#10;Power Points: {{ p.power_point_score | safe_float(1) }}{% endif %}{% if p.leading_lines_score %}&#10;Leading Lines: {{ p.leading_lines_score | safe_float(1) }}{% endif %}&#10;&#10;── Technical ──&#10;Exposure: {{ p.exposure_score | safe_float(1) }}&#10;Color: {{ p.color_score | safe_float(1) }}{% if p.contrast_score %}&#10;Contrast: {{ p.contrast_score | safe_float(1) }}{% endif %}{% if p.dynamic_range_stops %}&#10;Dynamic Range: {{ p.dynamic_range_stops | safe_float(1) }}{% endif %}{% if p.mean_saturation %}&#10;Saturation: {{ p.mean_saturation | safe_float(1) }}{% endif %}{% if p.noise_sigma %}&#10;Noise: {{ p.noise_sigma | safe_float(1) }}{% endif %}{% if p.isolation_bonus and p.isolation_bonus > 1.0 %}&#10;&#10;── Bonus ──&#10;Isolation: {{ p.isolation_bonus | safe_float(1) }}{% endif %}"
                        class="rounded object-cover cursor-pointer w-full sm:w-auto"
                        style="max-width: 100%"
                    >
                    <div class="selection-check hidden absolute top-1 right-1 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center">
                        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                        </svg>
                    </div>
                </div>

                <!-- Details -->
                <div class="mt-1.5 text-left">
                    <!-- Always visible: filename + aggregate score -->
                    <div class="flex justify-between text-[12px] items-center">
                        <div class="text-neutral-300 truncate font-medium">{{ p.filename }}</div>
                        <span class="text-green-400 font-medium">{{ p.aggregate | safe_float(1) }}</span>
                    </div>
                    <!-- Hidden on mobile -->
                    <div class="hidden sm:block">
                        <div class="flex justify-between items-center">
                            {% if sort_col == 'date_taken' or sort_col == 'aggregate' %}
                            <span class="text-green-400 font-bold text-base">{{ p.aggregate | safe_float(1) }}</span>
                            {% elif sort_col == 'shutter_speed' %}
                            <span class="text-green-400 font-bold text-base">{{ p[sort_col] | format_shutter }}</span>
                            {% elif sort_col == 'composition_pattern' %}
                            <span class="text-green-400 font-bold text-base">{{ (p[sort_col] or 'N/A') | replace('_', ' ') | title }}</span>
                            {% else %}
                            <span class="text-green-400 font-bold text-base">{{ p[sort_col] | safe_float(1) }}</span>
                            {% endif %}
                            <span>{% if p.is_burst_lead %}<span class="text-[10px] font-medium bg-green-900 text-green-400 px-1 rounded">{{ _('ui.badges.best') }}</span>{% endif %}{% if p.is_blink %} <span class="text-[10px] font-medium bg-amber-900 text-amber-400 px-1 rounded">{{ _('ui.badges.blink') }}</span>{% endif %}{% if p.is_monochrome %} <span class="text-[10px] font-medium bg-neutral-700 text-neutral-400 px-1 rounded">{{ _('ui.badges.bw') }}</span>{% endif %}</span>
                        </div>
                        {% if sort_col not in ['aggregate', 'date_taken'] %}
                        <div class="text-[10px] text-neutral-500 -mt-0.5">{{ sort_label }}</div>
                        {% endif %}
                        <div class="flex justify-between text-neutral-400 text-[12px]">
                            <span>{{ p.date_taken | format_date }}</span>
                        </div>
                        <div class="flex justify-between text-[12px] text-neutral-500">
                            <span>{{ p.focal_length or '?' }}mm f/{{ p.f_stop or '?' }}</span>
                            <span>ISO {{ p.iso or '?' }}</span>
                        </div>
                        {% if p.tags_list %}
                        <div class="flex flex-wrap gap-1 mt-1">
                            {% for tag in p.tags_list %}
                            <span class="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">{{ tag }}</span>
                            {% endfor %}
                        </div>
                        {% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>

    <!-- Infinite Scroll Loading Indicator -->
    <div id="scroll-loader" class="flex justify-center items-center gap-4 py-8 border-t border-neutral-800 {% if page >= total_pages %}hidden{% endif %}">
        <div id="scroll-spinner" class="hidden">
            <svg class="animate-spin h-6 w-6 text-green-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
        </div>
        <span id="scroll-status" class="text-neutral-400">
            {{ _('pagination.scroll_for_more') }} &middot; <span id="current-count">{{ photos|length }}</span> {{ _('ui.labels.of') }} {{ total_count }} {{ _('ui.labels.photos') }}
        </span>
    </div>
    <div id="scroll-end" class="{% if page < total_pages %}hidden{% endif %} flex justify-center items-center py-8 border-t border-neutral-800">
        <span class="text-neutral-500">{{ _('pagination.end_of_results') }} &middot; {{ total_count }} {{ _('ui.labels.photos') }}</span>
    </div>

    <!-- Selection Toolbar -->
    <div id="selection-toolbar" class="fixed bottom-4 left-1/2 transform -translate-x-1/2 translate-y-20 opacity-0 transition-all duration-300 z-50 bg-neutral-800 border border-neutral-700 rounded-lg shadow-xl px-2 sm:px-4 py-2 sm:py-3 flex items-center gap-2 sm:gap-4">
        <span class="text-neutral-300 hidden sm:inline"><span id="selection-count" class="text-green-400 font-bold">0</span> {{ _('ui.labels.selected') }}</span>
        <span class="text-green-400 font-bold sm:hidden" id="selection-count-mobile">0</span>
        <button onclick="copySelected()" class="bg-green-600 hover:bg-green-500 text-white px-2 sm:px-4 py-1 sm:py-1.5 rounded font-medium transition-colors flex items-center gap-1 sm:gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path>
            </svg>
            <span class="hidden sm:inline">{{ _('ui.buttons.copy') }}</span>
        </button>
        <button onclick="downloadSelected()" class="bg-green-600 hover:bg-green-500 text-white px-2 sm:px-4 py-1 sm:py-1.5 rounded font-medium transition-colors flex items-center gap-1 sm:gap-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
            </svg>
            <span class="hidden sm:inline">{{ _('ui.buttons.download') if _('ui.buttons.download') != 'ui.buttons.download' else 'Download' }}</span>
        </button>
        <button onclick="clearSelection()" class="text-neutral-400 hover:text-white px-1 sm:px-2 py-1 sm:py-1.5 transition-colors">
            <span class="hidden sm:inline">{{ _('ui.buttons.clear') }}</span>
            <svg class="w-4 h-4 sm:hidden" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        </button>
    </div>

    <!-- Copy Notification -->
    <div id="copy-notification" class="fixed bottom-4 right-4 bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg transform translate-y-20 opacity-0 transition-all duration-300 z-50">
        <span id="copy-notification-text">Copied!</span>
    </div>

    <!-- JavaScript -->
    <script>
        // Selection state
        const selectedPhotos = new Map();

        // Hover preview functionality (disabled on small screens)
        (function() {
            const preview = document.getElementById('hover-preview');
            const previewImg = preview.querySelector('img');
            let hoverTimeout = null;

            // Check if on small screen (mobile)
            const isSmallScreen = () => window.matchMedia('(max-width: 640px)').matches;

            function showPreview(e) {
                // Skip hover preview on small screens
                if (isSmallScreen()) return;

                const img = e.target;
                if (!img.src || !img.src.includes('/thumbnail')) return;

                // Clear any pending hide
                if (hoverTimeout) {
                    clearTimeout(hoverTimeout);
                    hoverTimeout = null;
                }

                // Set preview image source (use 640 since that's what we're loading now)
                previewImg.src = img.src.replace('size=640', 'size=480').replace('size=320', 'size=480');

                // Position preview
                positionPreview(e);

                // Show with slight delay to avoid flicker on quick mouse moves
                preview.classList.add('visible');
            }

            function hidePreview() {
                hoverTimeout = setTimeout(() => {
                    preview.classList.remove('visible');
                }, 50);
            }

            function positionPreview(e) {
                const padding = 20;
                const previewWidth = 480;
                const previewHeight = 480;

                let x = e.clientX + padding;
                let y = e.clientY - previewHeight / 2;

                // Adjust if preview would go off-screen to the right
                if (x + previewWidth > window.innerWidth - padding) {
                    x = e.clientX - previewWidth - padding;
                }

                // Adjust vertical position to stay in viewport
                if (y < padding) {
                    y = padding;
                } else if (y + previewHeight > window.innerHeight - padding) {
                    y = window.innerHeight - previewHeight - padding;
                }

                preview.style.left = x + 'px';
                preview.style.top = y + 'px';
            }

            // Delegate events to photo grid for efficiency
            document.getElementById('photo-grid').addEventListener('mouseenter', function(e) {
                if (e.target.tagName === 'IMG' && e.target.src.includes('/thumbnail')) {
                    showPreview(e);
                }
            }, true);

            document.getElementById('photo-grid').addEventListener('mouseleave', function(e) {
                if (e.target.tagName === 'IMG' && e.target.src.includes('/thumbnail')) {
                    hidePreview();
                }
            }, true);

            document.getElementById('photo-grid').addEventListener('mousemove', function(e) {
                if (e.target.tagName === 'IMG' && e.target.src.includes('/thumbnail') && preview.classList.contains('visible')) {
                    positionPreview(e);
                }
            }, true);

            // On small screens, copy data-tooltip to title for desktop users only
            // (Remove title attributes on mobile to prevent touch issues)
            if (!isSmallScreen()) {
                document.querySelectorAll('[data-tooltip]').forEach(el => {
                    el.title = el.dataset.tooltip;
                });
            }
        })();

        function toggleSortDir() {
            const dirInput = document.getElementById('sortDir');
            dirInput.value = dirInput.value === 'ASC' ? 'DESC' : 'ASC';
            document.getElementById('filterForm').submit();
        }

        // Escape key handler
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && selectedPhotos.size > 0) {
                clearSelection();
            }
        });

        // Toggle photo selection (keyed by path since filename is not unique)
        function toggleSelection(element, filename, path) {
            const checkmark = element.querySelector('.selection-check');
            const card = element.closest('.bg-neutral-900');

            if (selectedPhotos.has(path)) {
                selectedPhotos.delete(path);
                checkmark.classList.add('hidden');
                card.classList.remove('border-green-500', 'ring-2', 'ring-green-500');
                card.classList.add('border-neutral-800');
            } else {
                selectedPhotos.set(path, {element: element, filename: filename});
                checkmark.classList.remove('hidden');
                card.classList.remove('border-neutral-800');
                card.classList.add('border-green-500', 'ring-2', 'ring-green-500');
            }

            updateToolbar();
        }

        function updateToolbar() {
            const toolbar = document.getElementById('selection-toolbar');
            const countEl = document.getElementById('selection-count');
            const countElMobile = document.getElementById('selection-count-mobile');
            countEl.textContent = selectedPhotos.size;
            countElMobile.textContent = selectedPhotos.size;

            if (selectedPhotos.size > 0) {
                toolbar.classList.remove('translate-y-20', 'opacity-0');
                toolbar.classList.add('translate-y-0', 'opacity-100');
            } else {
                toolbar.classList.remove('translate-y-0', 'opacity-100');
                toolbar.classList.add('translate-y-20', 'opacity-0');
            }
        }

        function copySelected() {
            if (selectedPhotos.size === 0) return;

            const filenames = Array.from(selectedPhotos.values()).map(function(d) { return d.filename; }).join('\n');
            navigator.clipboard.writeText(filenames).then(function() {
                const count = selectedPhotos.size;
                showNotification('Copied ' + count + ' filename' + (count > 1 ? 's' : ''));
            }).catch(function(err) {
                console.error('Failed to copy: ', err);
            });
        }

        function downloadSelected() {
            if (selectedPhotos.size === 0) return;

            const paths = Array.from(selectedPhotos.keys());
            const count = paths.length;
            showNotification('Downloading ' + count + ' photo' + (count > 1 ? 's' : '') + '...');

            // Download files sequentially with small delay to avoid browser blocking
            let index = 0;
            function downloadNext() {
                if (index >= paths.length) {
                    showNotification('Downloaded ' + count + ' photo' + (count > 1 ? 's' : ''));
                    return;
                }
                const path = paths[index];
                const a = document.createElement('a');
                a.href = '/api/download?path=' + encodeURIComponent(path);
                a.download = '';
                a.style.display = 'none';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                index++;
                if (index < paths.length) {
                    setTimeout(downloadNext, 300);
                } else {
                    showNotification('Downloaded ' + count + ' photo' + (count > 1 ? 's' : ''));
                }
            }
            downloadNext();
        }

        function clearSelection() {
            selectedPhotos.forEach(function(data, path) {
                const checkmark = data.element.querySelector('.selection-check');
                const card = data.element.closest('.bg-neutral-900');
                checkmark.classList.add('hidden');
                card.classList.remove('border-green-500', 'ring-2', 'ring-green-500');
                card.classList.add('border-neutral-800');
            });
            selectedPhotos.clear();
            updateToolbar();
        }

        function showNotification(message) {
            const notification = document.getElementById('copy-notification');
            const text = document.getElementById('copy-notification-text');
            text.textContent = message;

            notification.classList.remove('translate-y-20', 'opacity-0');
            notification.classList.add('translate-y-0', 'opacity-100');

            setTimeout(function() {
                notification.classList.remove('translate-y-0', 'opacity-100');
                notification.classList.add('translate-y-20', 'opacity-0');
            }, {{ viewer_config.notification_duration_ms }});
        }

        // Infinite Scroll
        (function() {
            const photoGrid = document.getElementById('photo-grid');
            const scrollLoader = document.getElementById('scroll-loader');
            const scrollSpinner = document.getElementById('scroll-spinner');
            const scrollEnd = document.getElementById('scroll-end');
            const currentCountEl = document.getElementById('current-count');
            const cardWidth = {{ viewer_config.display.card_width_px }};
            const imageWidth = {{ viewer_config.display.image_width_px }};
            const personId = photoGrid.dataset.personId;

            let currentPage = parseInt(photoGrid.dataset.page);
            let totalPages = parseInt(photoGrid.dataset.totalPages);
            let sortCol = photoGrid.dataset.sortCol;
            let isLoading = false;
            let loadedCount = parseInt(currentCountEl.textContent);

            function safeFloat(val, decimals) {
                if (val === null || val === undefined || val === '') return '?';
                return parseFloat(val).toFixed(decimals);
            }

            function formatDate(val) {
                if (!val) return '';
                try {
                    const parts = val.substring(0, 19).split(' ');
                    const dateParts = parts[0].split(':');
                    const timeParts = parts[1] ? parts[1].split(':') : ['00', '00'];
                    return `${dateParts[2]}/${dateParts[1]}/${dateParts[0]} ${timeParts[0]}:${timeParts[1]}`;
                } catch (e) {
                    return val.split(' ')[0].replace(/:/g, '/');
                }
            }

            function formatShutter(val) {
                if (!val) return '?';
                if (val >= 1) return val.toFixed(1) + 's';
                return '1/' + Math.round(1/val);
            }

            function createPhotoCard(p) {
                const tags = (p.tags_list || []).map(tag =>
                    `<span class="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded">${tag}</span>`
                ).join('');

                const badges = [
                    p.is_burst_lead ? '<span class="text-[10px] font-medium bg-green-900 text-green-400 px-1 rounded">BEST</span>' : '',
                    p.is_blink ? '<span class="text-[10px] font-medium bg-amber-900 text-amber-400 px-1 rounded">BLINK</span>' : '',
                    p.is_monochrome ? '<span class="text-[10px] font-medium bg-neutral-700 text-neutral-400 px-1 rounded">B&W</span>' : ''
                ].filter(b => b).join(' ');

                const category = (p.category || 'others').replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase());
                let tooltip = `[${category}] Aggregate: ${safeFloat(p.aggregate, 1)}&#10;&#10;── Quality ──&#10;Aesthetic: ${safeFloat(p.aesthetic, 1)}`;
                if (p.quality_score) tooltip += `&#10;Quality: ${safeFloat(p.quality_score, 1)}`;
                if (p.face_count > 0) {
                    tooltip += `&#10;Face Quality: ${safeFloat(p.face_quality, 1)}`;
                    tooltip += `&#10;Face Sharpness: ${safeFloat(p.face_sharpness, 1)}`;
                    tooltip += `&#10;Eye Sharpness: ${safeFloat(p.eye_sharpness, 1)}`;
                }
                tooltip += `&#10;Tech Sharpness: ${safeFloat(p.tech_sharpness, 1)}`;
                tooltip += `&#10;&#10;── Composition ──&#10;Composition: ${safeFloat(p.comp_score, 1)}`;
                if (p.composition_pattern) tooltip += `&#10;Pattern: ${p.composition_pattern.replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase())}`;
                if (p.power_point_score) tooltip += `&#10;Power Points: ${safeFloat(p.power_point_score, 1)}`;
                if (p.leading_lines_score) tooltip += `&#10;Leading Lines: ${safeFloat(p.leading_lines_score, 1)}`;
                tooltip += `&#10;&#10;── Technical ──&#10;Exposure: ${safeFloat(p.exposure_score, 1)}&#10;Color: ${safeFloat(p.color_score, 1)}`;
                if (p.contrast_score) tooltip += `&#10;Contrast: ${safeFloat(p.contrast_score, 1)}`;
                if (p.dynamic_range_stops) tooltip += `&#10;Dynamic Range: ${safeFloat(p.dynamic_range_stops, 1)}`;
                if (p.mean_saturation) tooltip += `&#10;Saturation: ${safeFloat(p.mean_saturation, 1)}`;
                if (p.noise_sigma) tooltip += `&#10;Noise: ${safeFloat(p.noise_sigma, 1)}`;
                if (p.isolation_bonus && p.isolation_bonus > 1.0) tooltip += `&#10;&#10;── Bonus ──&#10;Isolation: ${safeFloat(p.isolation_bonus, 1)}`;

                let sortValue;
                if (sortCol === 'date_taken' || sortCol === 'aggregate') {
                    sortValue = `<span class="text-green-400 font-bold text-base">${safeFloat(p.aggregate, 1)}</span>`;
                } else if (sortCol === 'shutter_speed') {
                    sortValue = `<span class="text-green-400 font-bold text-base">${formatShutter(p[sortCol])}</span>`;
                } else if (sortCol === 'composition_pattern') {
                    const pattern = p[sortCol] || 'N/A';
                    sortValue = `<span class="text-green-400 font-bold text-base">${pattern.replace(/_/g, ' ')}</span>`;
                } else {
                    sortValue = `<span class="text-green-400 font-bold text-base">${safeFloat(p[sortCol], 1)}</span>`;
                }

                // JS-escape for onclick handler (escape backslashes and quotes)
                const jsEscape = (str) => str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"');

                return `
                <div class="photo-card bg-neutral-900 flex flex-col gap-1 rounded border border-neutral-800 p-1.5 hover:border-green-500 transition-all w-full sm:w-auto" style="max-width: 100%; --card-width: ${cardWidth}px">
                    <div class="flex-initial relative" onclick="toggleSelection(this, '${jsEscape(p.filename)}', '${jsEscape(p.path)}')">
                        <img src="/thumbnail?path=${encodeURIComponent(p.path)}&size=640" loading="lazy" data-tooltip="${tooltip}" class="rounded object-cover cursor-pointer w-full sm:w-auto" style="max-width: 100%">
                        <div class="selection-check hidden absolute top-1 right-1 w-6 h-6 bg-green-500 rounded-full flex items-center justify-center">
                            <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                            </svg>
                        </div>
                    </div>
                    <div class="mt-1.5 text-left">
                        <div class="flex justify-between text-[12px] items-center">
                            <div class="text-neutral-300 truncate font-medium">${p.filename}</div>
                            <span class="text-green-400 font-medium">${safeFloat(p.aggregate, 1)}</span>
                        </div>
                        <div class="hidden sm:block">
                            <div class="flex justify-between items-center">
                                ${sortValue}
                                <span>${badges}</span>
                            </div>
                            <div class="flex justify-between text-neutral-400 text-[12px]">
                                <span>${p.date_formatted || ''}</span>
                            </div>
                            <div class="flex justify-between text-[12px] text-neutral-500">
                                <span>${p.focal_length || '?'}mm f/${p.f_stop || '?'}</span>
                                <span>ISO ${p.iso || '?'}</span>
                            </div>
                            ${tags ? `<div class="flex flex-wrap gap-1 mt-1">${tags}</div>` : ''}
                        </div>
                    </div>
                </div>`;
            }

            async function loadMorePhotos() {
                if (isLoading || currentPage >= totalPages) return;

                isLoading = true;
                scrollSpinner.classList.remove('hidden');

                try {
                    const nextPage = currentPage + 1;
                    const params = new URLSearchParams(window.location.search);
                    params.set('page', nextPage);

                    const response = await fetch('/person/' + personId + '/api?' + params.toString());
                    const data = await response.json();

                    if (data.error) {
                        console.error('API error:', data.error);
                        return;
                    }

                    data.photos.forEach(photo => {
                        photoGrid.insertAdjacentHTML('beforeend', createPhotoCard(photo));
                    });

                    currentPage = data.page;
                    totalPages = data.total_pages;
                    loadedCount += data.photos.length;
                    currentCountEl.textContent = loadedCount;

                    if (!data.has_more) {
                        scrollLoader.classList.add('hidden');
                        scrollEnd.classList.remove('hidden');
                    }
                } catch (err) {
                    console.error('Failed to load photos:', err);
                } finally {
                    isLoading = false;
                    scrollSpinner.classList.add('hidden');
                }
            }

            function checkScroll() {
                if (isLoading || currentPage >= totalPages) return;

                const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
                const windowHeight = window.innerHeight;
                const docHeight = document.documentElement.scrollHeight;

                if (scrollTop + windowHeight >= docHeight - 300) {
                    loadMorePhotos();
                }
            }

            let scrollTimeout;
            window.addEventListener('scroll', function() {
                if (scrollTimeout) return;
                scrollTimeout = setTimeout(function() {
                    scrollTimeout = null;
                    checkScroll();
                }, 100);
            });

            setTimeout(checkScroll, 500);
        })();
    </script>
</body>
</html>
'''


# --- ROUTES ---
@person_bp.route('/person/<int:person_id>')
def person_page(person_id):
    """Display photos for a specific person."""
    person_info = get_person_info(person_id)
    if person_info is None:
        return "Person not found", 404

    try:
        photos, page, total_pages, total_count, sort_col, sort_label, params = _query_person_photos(person_id, request.args)
    except Exception as e:
        return f"Database Error: {e}", 500

    return render_template_string(
        PERSON_PAGE_TEMPLATE,
        person=person_info,
        photos=photos,
        params=params,
        sort_options_grouped=SORT_OPTIONS_GROUPED,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        sort_col=sort_col,
        sort_label=sort_label,
        viewer_config=VIEWER_CONFIG,
    )


@person_bp.route('/person/<int:person_id>/api')
def person_api(person_id):
    """API endpoint for infinite scroll on person page."""
    person_info = get_person_info(person_id)
    if person_info is None:
        return jsonify({'error': 'Person not found'}), 404

    try:
        photos, page, total_pages, total_count, sort_col, _, _ = _query_person_photos(person_id, request.args)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Add formatted date for JS rendering
    for photo in photos:
        photo['date_formatted'] = format_date(photo.get('date_taken'))

    return jsonify({
        'photos': photos,
        'page': page,
        'total_pages': total_pages,
        'total_count': total_count,
        'has_more': page < total_pages,
        'sort_col': sort_col,
    })
