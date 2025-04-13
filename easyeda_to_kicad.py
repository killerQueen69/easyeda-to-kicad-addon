# -*- coding: utf-8 -*-
from flask import Flask, request, render_template_string, send_from_directory, Response, abort
import subprocess
import os
import csv
import re
import logging
import time
import threading
import shutil
import glob
from datetime import datetime, timedelta
from queue import Queue
from collections import defaultdict
import json  # Import for reading config file

app = Flask(__name__)

# Configuration (Read from Home Assistant config)
OUTPUT_BASE = "/share/easyeda_output"
LIBRARY_ROOT_NAME = "library"
LIB_PREFIX = "easyeda_lib"
CLEANUP_DAYS = 7
DEFAULT_LIBRARY_NAME = f"{LIB_PREFIX}_default"
DISABLE_CLEANUP = False  # Initial default, will be updated from config

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('converter.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
log_queue = Queue()


class QueueHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_entry_cleaned = re.sub(r'\x1b\[[0-9;]*[mK]', '', log_entry)
        log_queue.put(log_entry_cleaned)


logging.getLogger().addHandler(QueueHandler())

# HTML Template (Removed the disable cleanup checkbox)
HTML = """<!doctype html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EasyEDA to KiCad Converter</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">
    <style>
        :root {
            --bg-color: #f5f8fa;
            --card-bg: #ffffff;
            --text-color: #333333;
            --border-color: #e1e4e8;
            --primary-color: #2563eb;
            --secondary-color: #4b5563;
            --success-color: #10b981;
            --hover-color: #dbeafe;
            --shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
            --pre-bg: #f0f0f0; /* Background for preformatted text */
        }

        .dark {
            --bg-color: #1a1a1a;
            --card-bg: #2d2d2d;
            --text-color: #f5f5f5;
            --border-color: #4a4a4a;
            --primary-color: #3b82f6;
            --secondary-color: #9ca3af;
            --success-color: #10b981;
            --hover-color: #374151;
            --shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
            --pre-bg: #252525; /* Dark background for preformatted text */
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            transition: background-color 0.3s, color 0.3s;
            padding: 0;
            margin: 0;
        }

        .container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 2rem;
        }

        h1 {
            font-size: 2rem; font-weight: 700; margin-bottom: 1.5rem; color: var(--primary-color);
            display: flex; align-items: center; gap: 0.5rem;
        }
        h3 {
            font-size: 1.25rem; font-weight: 600; margin: 2rem 0 1rem;
            display: flex; align-items: center; gap: 0.5rem;
        }

        .card {
            background-color: var(--card-bg); border-radius: 0.5rem; padding: 1.5rem;
            margin-bottom: 1.5rem; box-shadow: var(--shadow); border: 1px solid var(--border-color);
        }

        form { display: flex; flex-direction: column; gap: 1rem; }
        label { font-weight: 500; margin-bottom: 0.25rem; display: block; }
        input[type="text"], input[type="file"] {
            width: 100%; padding: 0.75rem; border-radius: 0.375rem; border: 1px solid var(--border-color);
            background-color: var(--card-bg); color: var(--text-color); font-size: 1rem; transition: border-color 0.3s;
        }
        input[type="text"]:focus, input[type="file"]:focus {
            outline: none; border-color: var(--primary-color); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.3);
        }
        input[type="submit"] {
            background-color: var(--primary-color); color: white; padding: 0.75rem 1.5rem; border: none;
            border-radius: 0.375rem; font-size: 1rem; font-weight: 500; cursor: pointer;
            transition: background-color 0.3s; margin-top: 0.5rem; display: flex; align-items: center;
            justify-content: center; gap: 0.5rem; width: max-content;
        }
        input[type="submit"]:hover { background-color: #1d4ed8; }

        .theme-toggle {
            position: fixed; top: 1rem; right: 1rem; background-color: var(--card-bg);
            color: var(--text-color); border: 1px solid var(--border-color); border-radius: 0.375rem;
            padding: 0.5rem; cursor: pointer; box-shadow: var(--shadow); z-index: 100;
            display: flex; align-items: center; justify-content: center; width: 40px; height: 40px;
            transition: all 0.3s;
        }
        .theme-toggle:hover { background-color: var(--hover-color); }

        #logs {
            background-color: var(--card-bg); border: 1px solid var(--border-color); border-radius: 0.375rem;
            padding: 1rem; height: 300px; overflow-y: auto; font-family: 'Consolas', 'Monaco', 'Menlo', monospace;
            font-size: 0.875rem; line-height: 1.5; white-space: pre-wrap; color: var(--text-color);
        }

        /* Styles for the directory listing */
        .directory-listing {
            background-color: var(--pre-bg);
            border: 1px solid var(--border-color);
            border-radius: 0.375rem;
            padding: 1rem;
            font-family: 'Consolas', 'Monaco', 'Menlo', monospace;
            font-size: 0.9rem;
            line-height: 1.5;
            white-space: pre; /* Important for alignment */
            overflow-x: auto; /* Add horizontal scroll if needed */
            color: var(--text-color);
        }
        .directory-listing a {
            color: var(--primary-color);
            text-decoration: none;
        }
        .directory-listing a:hover {
            text-decoration: underline;
        }

        .progress {
            background-color: var(--hover-color); color: var(--primary-color); padding: 0.75rem;
            border-radius: 0.375rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse { 0% { opacity: 0.7; } 50% { opacity: 1; } 100% { opacity: 0.7; } }

        .header-bar {
            background-color: var(--primary-color); color: white; padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); display: flex; align-items: center; justify-content: space-between;
        }
        .app-title {
            font-size: 1.5rem; margin: 0; font-weight: 700; color: white;
            display: flex; align-items: center; gap: 0.5rem;
        }

        .info-message {
            background-color: var(--hover-color); border-left: 4px solid var(--primary-color);
            padding: 0.75rem; margin-bottom: 1rem; border-radius: 0.25rem;
        }

        .status-message {
            margin-top: 1rem;
            padding: 0.75rem;
            border-radius: 0.375rem;
        }
        .status-success {
            background-color: #d1fae5;
            color: #065f46;
            border: 1px solid #065f46;
        }
        .status-duplicate {
            background-color: #fefcbf;
            color: #78350f;
            border: 1px solid #78350f;
        }
        .status-error {
            background-color: #fee2e2;
            color: #991b1b;
            border: 1px solid #991b1b;
        }
        .status-warning {
            background-color: #fffbeb;
            color: #a16207;
            border: 1px solid #a16207;
        }

        .cleanup-control {
            display: none; /* Hide the now removed control */
        }

        @media (max-width: 768px) {
            .container { padding: 1rem; }
            h1 { font-size: 1.5rem; }
            .card { padding: 1rem; }
        }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Theme toggle functionality
            const themeToggle = document.querySelector('.theme-toggle');
            const html = document.documentElement;
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme === 'dark') {
                html.classList.add('dark');
                themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
            } else {
                themeToggle.innerHTML = '<i class="fas fa-moon"></i>';
            }
            themeToggle.addEventListener('click', function() {
                html.classList.toggle('dark');
                if (html.classList.contains('dark')) {
                    localStorage.setItem('theme', 'dark');
                    themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
                } else {
                    localStorage.setItem('theme', 'light');
                    themeToggle.innerHTML = '<i class="fas fa-moon"></i>';
                }
            });

            // Show processing indicator on form submit
            const form = document.querySelector('form');
            const progress = document.getElementById('progress');
            if (form && progress) { // Add checks
                form.addEventListener('submit', function() {
                    progress.style.display = 'flex';
                });
            }

            // Live logs with server-sent events
            const logsDiv = document.getElementById('logs');
            if (logsDiv) { // Add check
                const evtSource = new EventSource('/logs');
                evtSource.onmessage = function(event) {
                    const logLine = document.createElement('div');
                    logLine.textContent = event.data;
                    logsDiv.appendChild(logLine);
                    logsDiv.scrollTop = logsDiv.scrollHeight;
                };
                evtSource.onerror = function(err) {
                    console.error("EventSource failed:", err);
                    if (logsDiv) {
                        // logsDiv.innerHTML += "<div>Log stream connection error. Please refresh.</div>";
                        // logsDiv.scrollTop = logsDiv.scrollHeight;
                    }
                    evtSource.close(); // Close the connection on error
                };
            }
        });
    </script>
</head>
<body>
    <div class="header-bar">
        <h1 class="app-title"><i class="fas fa-exchange-alt"></i> EasyEDA to KiCad Converter</h1>
        <div class="theme-toggle"><i class="fas fa-moon"></i></div>
    </div>

    <div class="container">
        <div class="card">
            {% if current_library %}
            <div class="info-message">
                <i class="fas fa-info-circle"></i> New components will be added to library: <strong>{{ current_library }}</strong>
            </div>
            {% endif %}

            <form method="post" enctype="multipart/form-data">
                <div id="progress" class="progress" style="display: none;">
                    <i class="fas fa-spinner fa-spin"></i> Processing, please wait...
                </div>

                <label for="lcsc_id">Enter LCSC ID:</label>
                <input type="text" name="lcsc_id" id="lcsc_id" placeholder="e.g. C123456">

                <label for="csv_file">Or Upload CSV (with 'LCSC' column):</label>
                <input type="file" name="csv_file" id="csv_file" accept=".csv">

                <input type="submit" value="Convert"><i class="fas fa-cogs"></i></input>
            </form>
        </div>

        {% if processing_results %}
        <div class="card">
            <h3><i class="fas fa-check-circle"></i> Processing Results</h3>
            {% if processing_results.processed %}
            <p class="status-message status-success"><i class="fas fa-check"></i> Successfully processed: {{ ', '.join(processing_results.processed) }}</p>
            {% endif %}
            {% if processing_results.skipped %}
            <p class="status-message status-duplicate"><i class="fas fa-exclamation-triangle"></i> Skipped (already processed): {{ ', '.join(processing_results.skipped) }}</p>
            {% endif %}
            {% if processing_results.failed %}
            <p class="status-message status-error"><i class="fas fa-times-circle"></i> Failed: {{ ', '.join(processing_results.failed) }}</p>
            {% endif %}
            {% if processing_results.warnings %}
            <p class="status-message status-warning"><i class="fas fa-exclamation-circle"></i> Warnings: {{ ', '.join(processing_results.warnings) }}</p>
            {% endif %}
        </div>
        {% elif output %}
        <div class="card">
            <p class="status-message status-warning"><i class="fas fa-exclamation-circle"></i> {{ output | safe }}</p>
        </div>
        {% endif %}

        <h3><i class="fas fa-folder-open"></i> Files in: {{ current_display_path }}</h3>
        <div class="card">
            <div class="directory-listing">
                {{ directory_listing_html | safe }}
            </div>
        </div>

        <h3><i class="fas fa-terminal"></i> Live Logs</h3>
        <div id="logs" class="card"></div>
    </div>
</body>
</html>
"""


def organize_files(temp_output_prefix, library_dir):
    logger.info(f"--- Starting file organization (New Logic) ---")
    logger.info(f"Using prefix: {temp_output_prefix}")
    logger.info(f"Target library dir: {library_dir}")
    copied_count = 0
    errors_encountered = False
    items_to_cleanup = []
    try:
        source_sym_path = temp_output_prefix + ".kicad_sym"
        source_fp_dir = temp_output_prefix + ".pretty"
        source_3d_dir = temp_output_prefix + ".3dshapes"
        dest_sym_dir = os.path.join(library_dir, "symbols")
        dest_fp_dir = os.path.join(library_dir, "footprints")
        dest_3d_dir = os.path.join(library_dir, "3dshapes")
        os.makedirs(dest_sym_dir, exist_ok=True)
        os.makedirs(dest_fp_dir, exist_ok=True)
        os.makedirs(dest_3d_dir, exist_ok=True)
        logger.debug(f"Ensured destination subdirs exist: {dest_sym_dir}, {dest_fp_dir}, {dest_3d_dir}")
        if os.path.isfile(source_sym_path):
            items_to_cleanup.append(source_sym_path)
            logger.debug(f"Found symbol file: {source_sym_path}")
            try:
                base_name = os.path.basename(source_sym_path)
                sanitized_name = re.sub(r'[<>:"/\\|?* ]', '_', base_name)
                dest_path = os.path.join(dest_sym_dir, sanitized_name)
                if os.path.exists(dest_path):
                    logger.warning(f"    Overwriting existing symbol: {os.path.relpath(dest_path, OUTPUT_BASE)}")
                shutil.copy2(source_sym_path, dest_path)
                logger.info(
                    f"    Successfully copied Symbol: {sanitized_name} to {os.path.relpath(dest_path, OUTPUT_BASE)}");
                copied_count += 1
            except Exception as e:
                logger.error(f"    !!! FAILED to copy symbol {source_sym_path} to {dest_path}: {e}", exc_info=True);
                errors_encountered = True
        else:
            logger.warning(f"Symbol file not found: {source_sym_path}")
        if os.path.isdir(source_fp_dir):
            items_to_cleanup.append(source_fp_dir)
            logger.debug(f"Found footprint directory: {source_fp_dir}")
            try:
                for filename in os.listdir(source_fp_dir):
                    if filename.endswith(".kicad_mod"):
                        src_fp_file = os.path.join(source_fp_dir, filename)
                        sanitized_name = re.sub(r'[<>:"/\\|?* ]', '_', filename)
                        dest_fp_file = os.path.join(dest_fp_dir, sanitized_name)
                        if os.path.isfile(src_fp_file):
                            if os.path.exists(dest_fp_file):
                                logger.warning(
                                    f"    Overwriting existing footprint: {os.path.relpath(dest_fp_file, OUTPUT_BASE)}")
                            shutil.copy2(src_fp_file, dest_fp_file)
                            logger.info(
                                f"    Successfully copied Footprint: {sanitized_name} to {os.path.relpath(dest_fp_file, OUTPUT_BASE)}");
                            copied_count += 1
            except Exception as e:
                logger.error(f"    !!! FAILED processing footprint dir {source_fp_dir}: {e}", exc_info=True);
                errors_encountered = True
        else:
            logger.warning(f"Footprint directory not found: {source_fp_dir}")
        if os.path.isdir(source_3d_dir):
            items_to_cleanup.append(source_3d_dir)
            logger.debug(f"Found 3D model directory: {source_3d_dir}")
            try:
                for filename in os.listdir(source_3d_dir):
                    if filename.endswith((".step", ".wrl")):
                        src_3d_file = os.path.join(source_3d_dir, filename)
                        dest_3d_file = os.path.join(dest_3d_dir, filename)
                        if os.path.isfile(src_3d_file):
                            if os.path.exists(dest_3d_file):
                                logger.warning(
                                    f"    Overwriting existing 3D model: {os.path.relpath(dest_3d_file, OUTPUT_BASE)}")
                            shutil.copy2(src_3d_file, dest_3d_file)
                            logger.info(
                                f"    Successfully copied 3D Model: {filename} to {os.path.relpath(dest_3d_file, OUTPUT_BASE)}");
                            copied_count += 1
            except Exception as e:
                logger.error(f"    !!! FAILED processing 3D model dir {source_3d_dir}: {e}", exc_info=True);
                errors_encountered = True
        else:
            logger.warning(f"3D model directory not found: {source_3d_dir}")
        original_empty_dir = temp_output_prefix
        if os.path.isdir(original_empty_dir):
            items_to_cleanup.append(original_empty_dir);
            logger.debug(f"Adding original empty dir to cleanup list: {original_empty_dir}")
        elif os.path.exists(original_empty_dir):
            logger.warning(f"Original temp path exists but is not a directory? {original_empty_dir}")
    except Exception as e:
        logger.error(f"--- ERROR during file organization setup for {temp_output_prefix} -> {library_dir}: {str(e)} ---",
                     exc_info=True);
        errors_encountered = True
    finally:
        logger.info(f"--- Cleaning up temporary items for prefix {os.path.basename(temp_output_prefix)} ---")
        for item_path in items_to_cleanup:
            try:
                if os.path.isfile(item_path):
                    os.remove(item_path);
                    logger.debug(f"    Removed temp file: {item_path}")
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path, ignore_errors=True);
                    logger.debug(f"    Removed temp directory: {item_path}")
                else:
                    logger.warning(f"    Item to cleanup not found or not file/dir: {item_path}")
            except Exception as cleanup_err:
                logger.error(f"    !!! FAILED to cleanup temporary item {item_path}: {cleanup_err}", exc_info=True);
                errors_encountered = True
        if copied_count == 0 and not errors_encountered:
            logger.warning(
                f"--- Organization finished: No files were copied for prefix {os.path.basename(temp_output_prefix)} (sources might be missing or empty).")
        elif errors_encountered:
            logger.error(
                f"--- Organization finished: Errors WERE encountered during processing for {os.path.basename(temp_output_prefix)}. Copied {copied_count} files.")
        else:
            logger.info(
                f"--- Organization finished successfully for {os.path.basename(temp_output_prefix)}. Copied {copied_count} files.")
    # Return True if organization happened without critical errors during copy/processing, False otherwise
    # We consider missing source files as non-critical error for this return value, but cleanup errors are critical.
    return not errors_encountered


def cleanup_old_files():
    while True:
        if DISABLE_CLEANUP:
            logger.info("Cleanup is disabled. Sleeping indefinitely.")
            time.sleep(3600 * 24 * 365)  # Sleep for a very long time
            continue
        try:
            cutoff = datetime.now() - timedelta(days=CLEANUP_DAYS)
            library_root_abs = os.path.abspath(os.path.join(OUTPUT_BASE, LIBRARY_ROOT_NAME))
            if not os.path.exists(library_root_abs):
                logger.info(f"Cleanup: Library root {library_root_abs} does not exist. Sleeping.")
                time.sleep(3600 * 24)
                continue
            logger.info(f"Starting cleanup for files older than {cutoff} in {library_root_abs}")
            cleaned_count = 0
            for root, dirs, files in os.walk(library_root_abs):
                for name in files:
                    try:
                        path = os.path.join(root, name)
                        mtime = datetime.fromtimestamp(os.path.getmtime(path))
                        if mtime < cutoff:
                            os.remove(path)
                            cleaned_count += 1
                            logger.info(f"Cleaned up file: {os.path.relpath(path, OUTPUT_BASE)}")
                    except FileNotFoundError:
                        logger.warning(f"Cleanup: File not found during iteration: {path}")
                    except Exception as e:
                        logger.error(f"Cleanup error processing file {path}: {str(e)}")
            logger.info(f"Cleanup finished. Removed {cleaned_count} old files.")
        except Exception as e:
            logger.error(f"General cleanup thread error: {str(e)}", exc_info=True)
        time.sleep(3600)


cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()


def get_latest_library_folder(library_root_abs):
    if not os.path.exists(library_root_abs):
        os.makedirs(library_root_abs, exist_ok=True)
        logger.info(f"Created library root directory: {library_root_abs}")
        return None
    folders = []
    try:
        for item in os.listdir(library_root_abs):
            full_path = os.path.join(library_root_abs, item)
            if os.path.isdir(full_path) and item.startswith(LIB_PREFIX):
                try:
                    mtime = os.path.getmtime(full_path)
                    folders.append({'name': item, 'mtime': mtime, 'path': full_path})
                except FileNotFoundError:
                    logger.warning(f"Could not get mtime for {full_path}, skipping.")
                    continue
    except Exception as e:
        logger.error(f"Error listing directories in {library_root_abs}: {e}", exc_info=True)
        return None
    if not folders:
        return None
    folders.sort(key=lambda x: x['mtime'], reverse=True)
    logger.debug(f"Found libraries: {folders}")
    return folders[0]['name']


def render_directory_listing(directory_path_abs, base_path_abs):
    output_lines = []
    items = []
    try:
        for name in os.listdir(directory_path_abs):
            full_path = os.path.join(directory_path_abs, name)
            try:
                stats = os.stat(full_path)
                is_dir = os.path.isdir(full_path)
                items.append({'name': name, 'is_dir': is_dir, 'mtime': stats.st_mtime, 'size': stats.st_size,
                              'full_path': full_path})
            except FileNotFoundError:
                continue
            except OSError as e:
                logger.error(f"OS error stating file {full_path}: {e}")
                continue
    except FileNotFoundError:
        return f"<pre>Error: Directory not found:\n{os.path.relpath(directory_path_abs, base_path_abs)}</pre>"
    except PermissionError:
        return f"<pre>Error: Permission denied accessing directory:\n{os.path.relpath(directory_path_abs, base_path_abs)}</pre>"
    except Exception as e:
        logger.error(f"Error listing directory {directory_path_abs}: {e}", exc_info=True)
        return f"<pre>Error: Could not list directory:\n{os.path.relpath(directory_path_abs, base_path_abs)}</pre>"
    items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    if os.path.abspath(directory_path_abs) != os.path.abspath(base_path_abs):
        parent_dir_abs = os.path.dirname(directory_path_abs)
        if os.path.abspath(parent_dir_abs).startswith(os.path.abspath(base_path_abs)):
            parent_rel_path = os.path.relpath(parent_dir_abs, base_path_abs)
            path_param = f"?path={parent_rel_path}" if parent_rel_path != "." else "/"
            time_str = " " * 19
            size_str = "<DIR>".rjust(8)
            link = f'<a href="{path_param}">..</a>'
            output_lines.append(f"{time_str} {size_str} {link}")
        else:
            logger.warning(f"Attempted to link parent '..' outside base directory from {directory_path_abs}")
    for item in items:
        try:
            time_str = datetime.fromtimestamp(item['mtime']).strftime('%m/%d/%Y %I:%M %p')
            relative_path = os.path.relpath(item['full_path'], base_path_abs)
            if item['is_dir']:
                size_str = "<DIR>".rjust(8)
                link = f'<a href="?path={relative_path}">{item["name"]}</a>'
            else:
                size_str = str(item['size']).rjust(8)
                download_relative_path = os.path.relpath(item['full_path'], OUTPUT_BASE)
                link = f'<a href="/download/{download_relative_path}" target="_blank">{item["name"]}</a>'
            output_lines.append(f"{time_str} {size_str} {link}")
        except Exception as e:
            logger.error(f"Error formatting item {item['name']}: {e}")
            output_lines.append(f"    Error processing item: {item['name']}")
    is_empty = not items
    has_only_dotdot = len(output_lines) == 1 and output_lines[0].endswith('..</a>')
    if is_empty and not has_only_dotdot:
        output_lines.append("    (Directory is empty)")
    elif has_only_dotdot and is_empty:
        output_lines.append("    (Directory is empty)")
    return "<pre>" + "\n".join(output_lines) + "</pre>"


@app.route('/logs')
def stream_logs():
    def generate():
        while True:
            try:
                while not log_queue.empty():
                    yield f"data: {log_queue.get()}\n\n"
                time.sleep(0.2)
            except GeneratorExit:
                logger.info("Log stream client disconnected.")
                return
            except Exception as e:
                logger.error(f"Error in log stream generator: {e}", exc_info=True)
                try:
                    yield f"data: Error in log stream: {e}\n\n"
                except Exception:
                    logger.error("Failed to yield error message to log stream client.")
                    return
                time.sleep(5)

    return Response(generate(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route("/", methods=["GET", "POST"])
def index():
    global DISABLE_CLEANUP

    # Read configuration at the start of the index function (or ideally, app startup)
    try:
        addon_config_path = '/config/addons/local/easyeda_to_kicad_web/config.json'
        if os.path.exists(addon_config_path):
            with open(addon_config_path, 'r') as f:
                addon_config = json.load(f)
                DISABLE_CLEANUP = addon_config.get('disable_auto_cleanup', False)
                logger.info(f"Automatic cleanup is {'disabled' if DISABLE_CLEANUP else 'enabled'} based on config.")
        else:
            logger.warning(f"Configuration file not found at: {addon_config_path}. Using default cleanup settings.")
    except Exception as e:
        logger.error(f"Error reading add-on configuration: {e}", exc_info=True)
        logger.warning("Using default cleanup settings.")

    output = ""  # For general status messages
    processing_results = {"processed": [], "skipped": [], "failed": [], "warnings": []}
    library_root_abs = os.path.abspath(os.path.join(OUTPUT_BASE, LIBRARY_ROOT_NAME))

    try:
        os.makedirs(library_root_abs, exist_ok=True)
        logger.debug(f"Library root directory: {library_root_abs}")
    except Exception as e:
        logger.error(f"Error creating/accessing library root directory {library_root_abs}: {str(e)}", exc_info=True)
        abort(500, description=f"Fatal Error: Cannot create or access library root directory at {library_root_abs}")

    current_library = get_latest_library_folder(library_root_abs) or DEFAULT_LIBRARY_NAME
    library_base_dir = os.path.join(library_root_abs, current_library)
    os.makedirs(library_base_dir, exist_ok=True)  # Ensure library directory exists

    processed_ids_log_path = os.path.join(library_base_dir, ".processed_lcsc_ids.log")
    processed_ids_set = set()

    # Read existing processed IDs
    try:
        if os.path.exists(processed_ids_log_path):
            with open(processed_ids_log_path, 'r') as f_log:
                processed_ids_set = {line.strip() for line in f_log if line.strip()}
            logger.info(
                f"Read {len(processed_ids_set)} processed IDs from {processed_ids_log_path} for library '{current_library}'")
    except Exception as read_log_err:
        logger.error(f"Error reading processed IDs log {processed_ids_log_path}: {read_log_err}", exc_info=True)
        processing_results["warnings"].append(
            f"Could not read processed IDs log for library '{current_library}'. Duplicate checks might be unreliable.")

    if request.method == "POST":
        lcsc_list_to_process = []
        skipped_ids = []
        input_ids = []  # To track all submitted IDs for final feedback

        lcsc_id_input = request.form.get('lcsc_id', '').strip()
        if lcsc_id_input:
            input_ids.append(lcsc_id_input)
            if re.match(r'^[Cc]\d+$', lcsc_id_input):
                if lcsc_id_input in processed_ids_set:
                    skipped_ids.append(lcsc_id_input)
                    logger.info(f"Skipping already processed LCSC ID: {lcsc_id_input} in library '{current_library}'")
                else:
                    lcsc_list_to_process.append(lcsc_id_input)
            else:
                processing_results["warnings"].append(
                    f"Invalid LCSC ID format: '{lcsc_id_input}'. Must be like C123456.")
                logger.warning(f"Invalid LCSC ID format: '{lcsc_id_input}'")

        if 'csv_file' in request.files and request.files['csv_file'].filename:
            csv_file = request.files['csv_file']
            try:
                csv_data = csv_file.read().decode('utf-8-sig')
                reader = csv.DictReader(csv_data.splitlines())
                lcsc_column_found = False
                if reader.fieldnames and 'LCSC' in reader.fieldnames:
                    lcsc_column_found = True
                    for row in reader:
                        _id = row.get('LCSC', '').strip()
                        if _id:
                            input_ids.append(_id)
                            if re.match(r'^[Cc]\d+$', _id):
                                if _id in processed_ids_set:
                                    skipped_ids.append(_id)
                                    logger.info(
                                        f"Skipping already processed LCSC ID from CSV: {_id} in library '{current_library}'")
                                else:
                                    lcsc_list_to_process.append(_id)
                            else:
                                processing_results["warnings"].append(f"Invalid LCSC ID format found in CSV: '{_id}'")
                                logger.warning(f"Invalid LCSC ID format found in CSV: '{_id}'")
                if not lcsc_column_found:
                    processing_results["warnings"].append("CSV file must contain an 'LCSC' column.")
                elif not lcsc_list_to_process and not skipped_ids:
                    processing_results["warnings"].append("No valid or new LCSC IDs found in CSV file.")
            except UnicodeDecodeError:
                processing_results["errors"].append("Could not read CSV file. Please ensure it is UTF-8 encoded.")
                logger.error("UnicodeDecodeError reading CSV")
            except csv.Error as csv_err:
                processing_results["errors"].append(f"Could not parse CSV file: {csv_err}")
                logger.error(f"CSV Error: {csv_err}")
            except Exception as read_err:
                processing_results["errors"].append(f"Could not process CSV file: {read_err}")
                logger.error(f"Error reading CSV file: {read_err}", exc_info=True)

        processed_ids = []
        failed_ids = []

        if lcsc_list_to_process:
            logger.info(f"Processing {len(lcsc_list_to_process)} new LCSC IDs into library folder '{current_library}'")
            log_queue.put(f"Starting conversion for {len(lcsc_list_to_process)} new LCSC IDs into library '{current_library}'...")
            for item_id in lcsc_list_to_process:
                temp_dir = None
                conversion_ok = False
                organization_ok = False
                try:
                    temp_base = os.path.join(OUTPUT_BASE, "temp")
                    os.makedirs(temp_base, exist_ok=True)
                    temp_dir = os.path.join(temp_base, f"temp_{item_id}_{int(time.time())}")
                    os.makedirs(temp_dir, exist_ok=True)

                    logger.info(f"Running easyeda2kicad for {item_id} using output prefix {temp_dir}")
                    log_queue.put(f"Converting {item_id}...")
                    process = subprocess.Popen(
                        ["easyeda2kicad", "--lcsc_id", item_id, "--full", "--output", temp_dir],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                        errors='replace'
                    )
                    for line in process.stdout:
                        clean_line = line.strip()
                        if clean_line:
                            logger.info(f"[{item_id}] {clean_line}")
                            log_queue.put(f"[{item_id}] {clean_line}")
                    process.wait()

                    if process.returncode != 0:
                        failed_ids.append(item_id)
                        err_msg = f"Conversion failed for {item_id} with exit code {process.returncode}"
                        logger.error(err_msg)
                        log_queue.put(f"[ERROR] {err_msg}")
                        # Attempt cleanup even on failure
                        organize_files(temp_dir, library_base_dir)  # Pass prefix
                    else:
                        conversion_ok = True
                        logger.info(f"Successfully converted {item_id}. Organizing files...");
                        log_queue.put(f"Conversion successful for {item_id}. Organizing...")
                        # Call the NEW organize_files, passing the prefix path
                        organization_ok = organize_files(temp_dir, library_base_dir)  # Returns True on success
                        if organization_ok:
                            processed_ids.append(item_id)
                            # Add to processed IDs log
                            try:
                                with open(processed_ids_log_path, 'a') as f_log:
                                    f_log.write(f"{item_id}\n")
                                processed_ids_set.add(item_id)  # Update the in-memory set
                                logger.info(
                                    f"Successfully processed and logged LCSC ID: {item_id} to {processed_ids_log_path}")
                                log_queue.put(f"Successfully added {item_id} to library '{current_library}'.")
                            except Exception as log_err:
                                logger.error(f"Error writing to processed IDs log {processed_ids_log_path}: {log_err}",
                                             exc_info=True)
                                processing_results["warnings"].append(
                                    f"Could not update processed IDs log for '{current_library}'.")
                        else:
                            failed_ids.append(item_id)
                            logger.error(f"File organization failed for {item_id}.")
                            log_queue.put(f"[ERROR] File organization failed for {item_id}.")

                except Exception as e:
                    failed_ids.append(item_id)
                    logger.error(f"Exception during processing of {item_id}: {str(e)}", exc_info=True)
                    log_queue.put(f"[ERROR] Exception during processing of {item_id}: {str(e)}")
                finally:
                    if temp_dir and os.path.exists(temp_dir):
                        try:
                            shutil.rmtree(temp_dir)
                            logger.debug(f"Cleaned up temporary directory: {temp_dir}")
                        except Exception as cleanup_err:
                            logger.error(f"Error cleaning up temporary directory {temp_dir}: {cleanup_err}",
                                         exc_info=True)

            processing_results["processed"].extend(processed_ids)
            processing_results["skipped"].extend(skipped_ids)
            processing_results["failed"].extend(failed_ids)
        elif output:
            processing_results["warnings"].append(output)
        elif skipped_ids:
            processing_results["skipped"].extend(skipped_ids)
        elif 'csv_file' in request.files and not request.files['csv_file'].filename and not lcsc_id_input:
            output = "Please enter an LCSC ID or upload a CSV file."
            processing_results["warnings"].append(output)
        elif not input_ids and request.method == "POST":
            output = "No LCSC IDs provided."
            processing_results["warnings"].append(output)

    # Determine the directory to display
    display_path_rel = request.args.get('path', '.')
    display_path_abs = os.path.abspath(os.path.join(library_base_dir, display_path_rel))

    # Security check to prevent Browse outside the library root
    if not display_path_abs.startswith(os.path.abspath(library_base_dir)):
        logger.warning(f"Attempted to access path outside library root: {display_path_abs}")
        abort(403)

    directory_listing_html = render_directory_listing(display_path_abs, library_base_dir)

    return render_template_string(HTML,
                                   current_library=current_library,
                                   directory_listing_html=directory_listing_html,
                                   current_display_path=os.path.relpath(display_path_abs, library_base_dir) if display_path_abs != library_base_dir else ".",
                                   output=output,
                                   processing_results=processing_results if request.method == "POST" else None)


@app.route('/download/<path:filename>')
def download_file(filename):
    full_path = os.path.join(OUTPUT_BASE, filename)
    if not os.path.isfile(full_path):
        abort(404)
    # Security check: Ensure the requested file is within the OUTPUT_BASE
    if not os.path.abspath(full_path).startswith(os.path.abspath(OUTPUT_BASE)):
        logger.warning(f"Attempted to download file outside OUTPUT_BASE: {full_path}")
        abort(403)
    return send_from_directory(OUTPUT_BASE, filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=7860)