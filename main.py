import os
import uuid
import asyncio
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import aiofiles

# Папка для хранения файлов
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Время жизни файла в днях
FILE_LIFETIME_DAYS = 3

# Временное хранилище метаданных (в реальном проекте — БД)
files_metadata = {}


async def cleanup_old_files():
    """Фоновая задача для удаления старых файлов."""
    while True:
        await asyncio.sleep(3600)
        now = datetime.now()
        expired_files = []
        
        for file_id, meta in files_metadata.items():
            upload_time = datetime.fromisoformat(meta["upload_time"])
            if now - upload_time > timedelta(days=FILE_LIFETIME_DAYS):
                expired_files.append(file_id)
        
        for file_id in expired_files:
            meta = files_metadata.pop(file_id)
            file_path = os.path.join(UPLOAD_DIR, meta["stored_filename"])
            if os.path.exists(file_path):
                os.remove(file_path)
        
        if expired_files:
            print(f"Очистка: удалено {len(expired_files)} устаревших файлов")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    cleanup_task = asyncio.create_task(cleanup_old_files())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title='Файлообменник', lifespan=lifespan)


def get_file_type(content_type: str, filename: str) -> str:
    """Определяет тип файла на основе MIME-типа и расширения."""
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    
    # Изображения
    if content_type.startswith("image/"):
        return "image"
    
    # Видео
    if content_type.startswith("video/") or ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"]:
        return "video"
    
    # Аудио
    if content_type.startswith("audio/") or ext in [".mp3", ".wav", ".flac", ".aac", ".m4a"]:
        return "audio"
    
    # Текстовые файлы (включая документы)
    text_mimes = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/rtf",
    ]
    
    text_exts = [
        ".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", 
        ".odt", ".ods", ".odp", ".rtf",
        ".py", ".js", ".html", ".css", ".json", ".xml", ".md", ".csv", 
        ".log", ".yaml", ".yml", ".sh", ".bash", ".ini", ".cfg", ".conf", ".env",
        ".sql", ".php", ".java", ".cpp", ".c", ".h", ".rb", ".go", ".rs", ".ts",
        ".tex", ".bib", ".r", ".m", ".swift", ".kt", ".scala", ".pl"
    ]
    
    if content_type.startswith("text/") or content_type in text_mimes or ext in text_exts:
        return "text"
    
    # Архивы
    archive_mimes = [
        "application/zip",
        "application/x-zip-compressed",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/gzip",
        "application/x-7z-compressed",
        "application/x-bzip2",
    ]
    archive_exts = [".zip", ".rar", ".tar", ".gz", ".7z", ".bz2"]
    
    if content_type in archive_mimes or ext in archive_exts:
        return "archive"
    
    # Всё остальное
    return "other"


@app.post('/upload')
async def upload_file(file: UploadFile = File(..., description='Файл')):
    """
    Загружает файл на сервер.
    После успешной загрузки перенаправляет на главную страницу.
    """
    file_id = str(uuid.uuid4())
    original_filename = file.filename
    ext = os.path.splitext(original_filename)[1] if original_filename else ""
    stored_filename = f"{file_id}{ext}"

    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)

    content_type = file.content_type or ""
    file_type = get_file_type(content_type, original_filename)

    files_metadata[file_id] = {
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "size_bytes": len(content),
        "upload_time": datetime.now().isoformat(),
        "content_type": content_type,
        "file_type": file_type,
        "expires_at": (datetime.now() + timedelta(days=FILE_LIFETIME_DAYS)).isoformat(),
    }

    return RedirectResponse(url="/", status_code=303)


@app.get('/files/{file_id}')
async def download_file(file_id: str):
    """
    Скачивание файла по его идентификатору.
    Возвращает ошибку 404, если файл не найден.
    """
    if file_id not in files_metadata:
        raise HTTPException(status_code=404, detail="Файл не найден в системе")

    meta = files_metadata[file_id]
    file_path = os.path.join(UPLOAD_DIR, meta['stored_filename'])

    if not os.path.exists(file_path):
        # Если файла нет на диске, удаляем метаданные
        files_metadata.pop(file_id, None)
        raise HTTPException(status_code=404, detail="Файл отсутствует на диске и был удален из списка")

    return FileResponse(
        path=file_path,
        filename=meta['original_filename'],
        media_type=meta.get('content_type', 'application/octet-stream')
    )


@app.get("/files")
async def list_files(file_type: Optional[str] = Query(None, description="Тип файлов для фильтрации")):
    """Возвращает список всех загруженных файлов с возможностью фильтрации по типу."""
    now = datetime.now()
    result = []
    invalid_files = []
    
    for fid, meta in files_metadata.items():
        # Проверяем, существует ли файл на диске
        file_path = os.path.join(UPLOAD_DIR, meta['stored_filename'])
        if not os.path.exists(file_path):
            invalid_files.append(fid)
            continue
            
        if file_type and file_type != "all" and meta["file_type"] != file_type:
            continue
            
        upload_time = datetime.fromisoformat(meta["upload_time"])
        expires_at = datetime.fromisoformat(meta["expires_at"])
        time_left = expires_at - now
        
        if time_left.total_seconds() <= 0:
            hours_left = 0
            minutes_left = 0
        else:
            hours_left = int(time_left.total_seconds() // 3600)
            minutes_left = int((time_left.total_seconds() % 3600) // 60)
        
        result.append({
            "file_id": fid,
            "original_filename": meta["original_filename"],
            "size_bytes": meta["size_bytes"],
            "upload_time": meta["upload_time"],
            "download_url": f"/files/{fid}",
            "file_type": meta["file_type"],
            "content_type": meta["content_type"],
            "expires_at": meta["expires_at"],
            "time_left_hours": hours_left,
            "time_left_minutes": minutes_left,
        })
    
    # Удаляем метаданные несуществующих файлов
    for fid in invalid_files:
        files_metadata.pop(fid, None)
    
    result.sort(key=lambda x: x["upload_time"], reverse=True)
    
    return {"files": result, "removed_count": len(invalid_files)}


@app.delete('/files/{file_id}')
async def delete_file(file_id: str):
    """Удаляет файл по ID."""
    if file_id not in files_metadata:
        raise HTTPException(status_code=404, detail='Файл не найден')
    
    meta = files_metadata.pop(file_id)
    file_path = os.path.join(UPLOAD_DIR, meta["stored_filename"])
    
    if os.path.exists(file_path):
        os.remove(file_path)
    
    return {"message": f"Файл '{meta['original_filename']}' удалён"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """HTML-страница с предпросмотром файлов и фильтрацией."""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Файлообменник</title>
        <meta charset="utf-8">
        <style>
            * {{ box-sizing: border-box; }}
            body {{ font-family: Arial, sans-serif; margin: 20px; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
            .header h1 {{ margin: 0; }}
            .header p {{ margin: 5px 0 0; opacity: 0.9; }}
            .upload-section {{ background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .filter-bar {{ background: white; padding: 15px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
            .filter-btn {{ padding: 8px 16px; border: 2px solid #667eea; background: white; color: #667eea; border-radius: 20px; cursor: pointer; font-size: 14px; transition: all 0.2s; white-space: nowrap; }}
            .filter-btn:hover {{ background: #f0f0ff; }}
            .filter-btn.active {{ background: #667eea; color: white; }}
            .filter-btn .count {{ margin-left: 5px; font-size: 12px; opacity: 0.8; }}
            .file-item {{ margin: 10px 0; padding: 15px; background: white; border-radius: 8px; display: flex; align-items: center; gap: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: transform 0.2s; }}
            .file-item:hover {{ transform: translateY(-2px); box-shadow: 0 4px 8px rgba(0,0,0,0.15); }}
            .file-item.expiring-soon {{ border-left: 4px solid #ffc107; }}
            .file-item.expired {{ border-left: 4px solid #dc3545; opacity: 0.7; }}
            .file-item img {{ width: 80px; height: 60px; object-fit: cover; border-radius: 5px; cursor: pointer; }}
            .file-item video {{ width: 80px; height: 60px; object-fit: cover; border-radius: 5px; cursor: pointer; }}
            button {{ padding: 8px 15px; cursor: pointer; border: none; border-radius: 5px; background: #007bff; color: white; font-size: 14px; transition: background 0.2s; }}
            button:hover {{ background: #0056b3; }}
            button.delete {{ background: #dc3545; }}
            button.delete:hover {{ background: #c82333; }}
            .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; }}
            .modal-content {{ position: relative; margin: 2% auto; padding: 20px; background: white; width: 90%; max-width: 1000px; max-height: 90vh; overflow: auto; border-radius: 10px; }}
            .modal img {{ max-width: 100%; max-height: 80vh; display: block; margin: 0 auto; }}
            .modal video {{ max-width: 100%; max-height: 80vh; display: block; margin: 0 auto; }}
            .modal audio {{ width: 100%; margin: 20px 0; }}
            .modal pre {{ white-space: pre-wrap; word-wrap: break-word; background: #f5f5f5; padding: 20px; border-radius: 5px; max-height: 70vh; overflow: auto; font-size: 14px; line-height: 1.5; }}
            .close {{ position: absolute; top: 10px; right: 20px; font-size: 35px; cursor: pointer; color: #333; z-index: 1001; }}
            .close:hover {{ color: #000; }}
            .preview-link {{ color: #007bff; cursor: pointer; text-decoration: underline; }}
            .preview-link:hover {{ color: #0056b3; }}
            .file-info {{ flex-grow: 1; }}
            .file-info strong {{ font-size: 16px; display: block; margin-bottom: 5px; word-break: break-all; }}
            .file-info small {{ color: #666; display: block; margin-top: 3px; }}
            .file-actions {{ display: flex; gap: 10px; align-items: center; }}
            .video-thumb {{ position: relative; cursor: pointer; }}
            .video-thumb::after {{ content: "▶"; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 20px; color: white; text-shadow: 0 0 5px rgba(0,0,0,0.5); }}
            .audio-icon {{ font-size: 40px; cursor: pointer; }}
            .time-badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; }}
            .time-badge.green {{ background: #d4edda; color: #155724; }}
            .time-badge.yellow {{ background: #fff3cd; color: #856404; }}
            .time-badge.red {{ background: #f8d7da; color: #721c24; }}
            .type-badge {{ display: inline-block; padding: 2px 6px; border-radius: 10px; font-size: 11px; background: #e9ecef; color: #495057; margin-left: 5px; }}
            .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
            .stat-card {{ background: white; padding: 15px; border-radius: 8px; text-align: center; flex: 1; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .stat-card .number {{ font-size: 24px; font-weight: bold; color: #667eea; }}
            .stat-card .label {{ color: #666; font-size: 14px; margin-top: 5px; }}
            .no-files {{ color: #999; text-align: center; padding: 40px; background: white; border-radius: 8px; }}
            .file-icon {{ font-size: 40px; width: 80px; text-align: center; }}
            
            /* Стили для уведомлений */
            .notification {{ 
                position: fixed; 
                top: 20px; 
                right: 20px; 
                padding: 15px 20px; 
                border-radius: 8px; 
                color: white; 
                font-weight: bold; 
                z-index: 2000; 
                animation: slideIn 0.3s ease-out;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                max-width: 400px;
            }}
            .notification.error {{ background: #dc3545; }}
            .notification.warning {{ background: #ffc107; color: #333; }}
            .notification.success {{ background: #28a745; }}
            .notification.info {{ background: #17a2b8; }}
            
            @keyframes slideIn {{
                from {{ transform: translateX(100%); opacity: 0; }}
                to {{ transform: translateX(0); opacity: 1; }}
            }}
            @keyframes slideOut {{
                from {{ transform: translateX(0); opacity: 1; }}
                to {{ transform: translateX(100%); opacity: 0; }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📁 Файлообменник</h1>
            <p>Файлы автоматически удаляются через {FILE_LIFETIME_DAYS} дня</p>
        </div>
        
        <div class="upload-section">
            <h2>Загрузить файл</h2>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" required style="padding: 10px; margin-right: 10px;">
                <button type="submit">Загрузить</button>
            </form>
        </div>
        
        <div class="filter-bar" id="filter-bar">
            <span style="font-weight: bold; margin-right: 10px;">Фильтр:</span>
        </div>
        
        <div class="stats" id="stats"></div>
        
        <h2>Список файлов <span id="filter-label"></span></h2>
        <div id="file-list"></div>
        
        <div id="preview-modal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closePreview()">&times;</span>
                <div id="preview-content"></div>
            </div>
        </div>
        
        <!-- Контейнер для уведомлений -->
        <div id="notifications"></div>

        <script>
            let currentFilter = 'all';
            let allFiles = [];
            
            const filterTypes = {{
                'all': '📋 Все',
                'image': '🖼️ Изображения',
                'video': '🎬 Видео',
                'audio': '🎵 Аудио',
                'text': '📄 Текстовые',
                'archive': '📦 Архивы',
                'other': '📁 Другие'
            }};
            
            const typeIcons = {{
                'image': '🖼️',
                'video': '🎬',
                'audio': '🎵',
                'text': '📄',
                'archive': '📦',
                'other': '📁'
            }};
            
            // Функция для показа уведомлений
            function showNotification(message, type = 'error', duration = 5000) {{
                const container = document.getElementById('notifications');
                const notification = document.createElement('div');
                notification.className = `notification ${{type}}`;
                notification.textContent = message;
                container.appendChild(notification);
                
                setTimeout(() => {{
                    notification.style.animation = 'slideOut 0.3s ease-out';
                    setTimeout(() => {{
                        container.removeChild(notification);
                    }}, 300);
                }}, duration);
            }}
            
            // Создаем кнопки фильтров
            const filterBar = document.getElementById('filter-bar');
            Object.entries(filterTypes).forEach(([type, label]) => {{
                const btn = document.createElement('button');
                btn.className = 'filter-btn' + (type === currentFilter ? ' active' : '');
                btn.setAttribute('data-filter', type);
                btn.innerHTML = label + '<span class="count"></span>';
                btn.onclick = function() {{ setFilter(type); }};
                filterBar.appendChild(btn);
            }});
            
            function setFilter(type) {{
                currentFilter = type;
                
                document.querySelectorAll('.filter-btn').forEach(btn => {{
                    btn.classList.remove('active');
                }});
                const activeBtn = document.querySelector(`.filter-btn[data-filter="${{type}}"]`);
                if (activeBtn) {{
                    activeBtn.classList.add('active');
                }}
                
                loadFiles();
            }}
            
            function updateFilterCounts() {{
                const counts = {{}};
                allFiles.forEach(f => {{
                    counts[f.file_type] = (counts[f.file_type] || 0) + 1;
                }});
                counts['all'] = allFiles.length;
                
                document.querySelectorAll('.filter-btn').forEach(btn => {{
                    const type = btn.getAttribute('data-filter');
                    const countSpan = btn.querySelector('.count');
                    if (countSpan && counts[type] !== undefined) {{
                        countSpan.textContent = ` (${{counts[type]}})`;
                    }} else if (countSpan) {{
                        countSpan.textContent = ' (0)';
                    }}
                }});
            }}
            
            async function loadFiles() {{
                try {{
                    const url = currentFilter === 'all' ? '/files' : `/files?file_type=${{currentFilter}}`;
                    const resp = await fetch(url);
                    const data = await resp.json();
                    allFiles = data.files;
                    
                    // Показываем уведомление, если были удалены несуществующие файлы
                    if (data.removed_count > 0) {{
                        showNotification(`Было автоматически удалено ${{data.removed_count}} несуществующих файлов`, 'warning', 4000);
                    }}
                    
                    updateFilterCounts();
                    renderFiles();
                }} catch (e) {{
                    console.error('Ошибка загрузки файлов:', e);
                    showNotification('Ошибка при загрузке списка файлов', 'error');
                }}
            }}
            
            // Переопределяем функцию скачивания для обработки ошибок
            async function downloadFile(fileId, fileName) {{
                try {{
                    const resp = await fetch(`/files/${{fileId}}`);
                    
                    if (!resp.ok) {{
                        if (resp.status === 404) {{
                            const errorData = await resp.json();
                            showNotification(`Файл "${{fileName}}" не найден и будет удален из списка`, 'error', 5000);
                            // Обновляем список, чтобы удалить файл
                            setTimeout(() => loadFiles(), 500);
                        }} else {{
                            showNotification(`Ошибка при скачивании файла: ${{resp.statusText}}`, 'error');
                        }}
                        return;
                    }}
                    
                    // Если всё ок, скачиваем файл
                    const blob = await resp.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = fileName;
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                    
                }} catch (e) {{
                    console.error('Ошибка при скачивании:', e);
                    showNotification('Ошибка при скачивании файла. Возможно, файл поврежден.', 'error');
                    // Обновляем список на всякий случай
                    setTimeout(() => loadFiles(), 500);
                }}
            }}
            
            async function downloadFileById(fileId) {{
                // Находим имя файла по ID
                const file = allFiles.find(f => f.file_id === fileId);
                const fileName = file ? file.original_filename : 'file';
                await downloadFile(fileId, fileName);
            }}
            
            function renderFiles() {{
                const list = document.getElementById('file-list');
                const stats = document.getElementById('stats');
                const filterLabel = document.getElementById('filter-label');
                
                list.innerHTML = '';
                
                if (allFiles.length === 0) {{
                    list.innerHTML = '<div class="no-files">Нет файлов</div>';
                    stats.innerHTML = '';
                    filterLabel.textContent = currentFilter !== 'all' ? '— ' + filterTypes[currentFilter] : '';
                    return;
                }}
                
                filterLabel.textContent = currentFilter !== 'all' ? '— ' + filterTypes[currentFilter] : '';
                
                const totalSize = allFiles.reduce((sum, f) => sum + f.size_bytes, 0);
                const expiringSoon = allFiles.filter(f => f.time_left_hours < 6 && f.time_left_hours > 0).length;
                
                stats.innerHTML = `
                    <div class="stat-card">
                        <div class="number">${{allFiles.length}}</div>
                        <div class="label">Файлов</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${{formatSize(totalSize)}}</div>
                        <div class="label">Общий размер</div>
                    </div>
                    <div class="stat-card">
                        <div class="number">${{expiringSoon}}</div>
                        <div class="label">Истекает скоро</div>
                    </div>
                `;
                
                allFiles.forEach(f => {{
                    const div = document.createElement('div');
                    div.className = 'file-item';
                    
                    const timeLeftHours = f.time_left_hours;
                    const timeLeftMinutes = f.time_left_minutes;
                    
                    if (timeLeftHours === 0 && timeLeftMinutes === 0) {{
                        div.classList.add('expired');
                    }} else if (timeLeftHours < 6) {{
                        div.classList.add('expiring-soon');
                    }}
                    
                    let iconHtml = '';
                    
                    switch(f.file_type) {{
                        case 'image':
                            iconHtml = `<img src="/files/${{f.file_id}}" alt="${{f.original_filename}}" onclick="openPreview('${{f.file_id}}', 'image', '${{f.content_type}}')" loading="lazy" onerror="this.onerror=null; this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🖼️</text></svg>';">`;
                            break;
                        case 'video':
                            iconHtml = `<div class="video-thumb" onclick="openPreview('${{f.file_id}}', 'video', '${{f.content_type}}')">
                                <video src="/files/${{f.file_id}}" preload="metadata"></video>
                            </div>`;
                            break;
                        case 'audio':
                            iconHtml = `<div class="audio-icon" onclick="openPreview('${{f.file_id}}', 'audio', '${{f.content_type}}')">🎵</div>`;
                            break;
                        case 'text':
                            const ext = f.original_filename.split('.').pop().toLowerCase();
                            const previewableExts = ['txt', 'py', 'js', 'html', 'css', 'json', 'xml', 'md', 'csv', 'log', 'yaml', 'yml', 'sh', 'bash', 'ini', 'cfg', 'conf', 'env', 'sql', 'php', 'java', 'cpp', 'c', 'h', 'rb', 'go', 'rs', 'ts'];
                            if (previewableExts.includes(ext)) {{
                                iconHtml = `<span class="preview-link" onclick="openPreview('${{f.file_id}}', 'text', '${{f.content_type}}')">📄</span>`;
                            }} else {{
                                iconHtml = `<div class="file-icon">📄</div>`;
                            }}
                            break;
                        default:
                            iconHtml = `<div class="file-icon">${{typeIcons[f.file_type] || '📁'}}</div>`;
                    }}
                    
                    let timeString = '';
                    let timeBadgeClass = '';
                    
                    if (timeLeftHours === 0 && timeLeftMinutes === 0) {{
                        timeString = 'Истекает (удаляется)';
                        timeBadgeClass = 'red';
                    }} else if (timeLeftHours < 1) {{
                        timeString = `Осталось ${{timeLeftMinutes}} мин.`;
                        timeBadgeClass = 'red';
                    }} else if (timeLeftHours < 6) {{
                        timeString = `Осталось ${{timeLeftHours}} ч. ${{timeLeftMinutes}} мин.`;
                        timeBadgeClass = 'yellow';
                    }} else if (timeLeftHours < 24) {{
                        timeString = `Осталось ${{timeLeftHours}} ч.`;
                        timeBadgeClass = 'yellow';
                    }} else {{
                        const days = Math.floor(timeLeftHours / 24);
                        const hours = timeLeftHours % 24;
                        timeString = `Осталось ${{days}} д. ${{hours}} ч.`;
                        timeBadgeClass = 'green';
                    }}
                    
                    div.innerHTML = `
                        <div style="min-width: 80px; display: flex; align-items: center; justify-content: center;">
                            ${{iconHtml}}
                        </div>
                        <div class="file-info">
                            <strong title="${{f.original_filename}}">
                                ${{f.original_filename}}
                                <span class="type-badge">${{filterTypes[f.file_type] || f.file_type}}</span>
                            </strong>
                            <small>
                                ${{formatSize(f.size_bytes)}} • Загружен ${{new Date(f.upload_time).toLocaleString('ru-RU')}}
                            </small>
                            <small>
                                <span class="time-badge ${{timeBadgeClass}}">⏰ ${{timeString}}</span>
                            </small>
                        </div>
                        <div class="file-actions">
                            <button onclick="downloadFileById('${{f.file_id}}')">Скачать</button>
                            <button class="delete" onclick="deleteFile('${{f.file_id}}')">Удалить</button>
                        </div>
                    `;
                    
                    list.appendChild(div);
                }});
            }}
            
            function formatSize(bytes) {{
                if (bytes === 0) return '0 B';
                const k = 1024;
                const sizes = ['B', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
            }}
            
            async function openPreview(fileId, type, mimeType) {{
                const modal = document.getElementById('preview-modal');
                const content = document.getElementById('preview-content');
                
                try {{
                    const resp = await fetch(`/files/${{fileId}}`);
                    
                    if (!resp.ok) {{
                        if (resp.status === 404) {{
                            showNotification('Файл не найден. Он будет удален из списка.', 'error', 4000);
                            closePreview();
                            setTimeout(() => loadFiles(), 500);
                        }} else {{
                            showNotification('Ошибка при загрузке предпросмотра', 'error');
                        }}
                        return;
                    }}
                    
                    switch(type) {{
                        case 'image':
                            const blob = await resp.blob();
                            const url = URL.createObjectURL(blob);
                            content.innerHTML = `<img src="${{url}}" alt="Предпросмотр">`;
                            break;
                        case 'video':
                            content.innerHTML = `<video controls autoplay><source src="/files/${{fileId}}" type="${{mimeType}}">Ваш браузер не поддерживает видео.</video>`;
                            break;
                        case 'audio':
                            content.innerHTML = `<div style="text-align: center; padding: 40px;"><h3>🎵 Аудиоплеер</h3><audio controls autoplay style="width: 100%; margin: 20px 0;"><source src="/files/${{fileId}}" type="${{mimeType}}">Ваш браузер не поддерживает аудио.</audio></div>`;
                            break;
                        case 'text':
                            const text = await resp.text();
                            const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                            content.innerHTML = `<pre>${{escaped}}</pre>`;
                            break;
                    }}
                    
                    modal.style.display = 'block';
                    document.body.style.overflow = 'hidden';
                }} catch (e) {{
                    console.error('Ошибка предпросмотра:', e);
                    showNotification('Ошибка при загрузке предпросмотра', 'error');
                }}
            }}
            
            function closePreview() {{
                const modal = document.getElementById('preview-modal');
                const content = document.getElementById('preview-content');
                const media = content.querySelector('video, audio');
                if (media) {{
                    media.pause();
                    media.src = '';
                }}
                content.innerHTML = '';
                modal.style.display = 'none';
                document.body.style.overflow = 'auto';
            }}
            
            async function deleteFile(id) {{
                if (confirm('Вы уверены, что хотите удалить файл?')) {{
                    try {{
                        const resp = await fetch(`/files/${{id}}`, {{ method: 'DELETE' }});
                        if (resp.ok) {{
                            showNotification('Файл успешно удален', 'success', 3000);
                            loadFiles();
                        }} else {{
                            showNotification('Ошибка при удалении файла', 'error');
                        }}
                    }} catch (e) {{
                        showNotification('Ошибка при удалении файла', 'error');
                    }}
                }}
            }}
            
            document.getElementById('preview-modal').onclick = function(event) {{
                if (event.target === this) closePreview();
            }}
            
            document.addEventListener('keydown', function(event) {{
                if (event.key === 'Escape') closePreview();
            }});
            
            window.onload = function() {{
                loadFiles();
            }};
            
            setInterval(loadFiles, 30000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)