import os
import uuid
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
import aiofiles

app = FastAPI(title='Файлообменник')

# Папка для хранения файлов
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Временное хранилище метаданных (в реальном проекте — БД)
files_metadata = {}


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

    # Определяем тип файла для предпросмотра
    content_type = file.content_type or ""
    file_type = "other"
    
    if content_type.startswith("image/"):
        file_type = "image"
    elif content_type.startswith("video/"):
        file_type = "video"
    elif content_type.startswith("audio/"):
        file_type = "audio"
    elif content_type.startswith("text/") or ext.lower() in [".txt", ".py", ".js", ".html", ".css", ".json", ".xml", ".md", ".csv", ".log", ".yaml", ".yml", ".sh", ".bash", ".ini", ".cfg"]:
        file_type = "text"
    # Дополнительно проверяем по расширению, если MIME-тип не определился
    elif ext.lower() in [".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv"]:
        file_type = "video"
    elif ext.lower() in [".mp3", ".wav", ".ogg", ".flac", ".aac"]:
        file_type = "audio"

    files_metadata[file_id] = {
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "size_bytes": len(content),
        "upload_time": datetime.now().isoformat(),
        "content_type": content_type,
        "file_type": file_type,
    }

    return RedirectResponse(url="/", status_code=303)


@app.get('/files/{file_id}')
async def download_file(file_id: str):
    """
    Скачивание файла по его идентификатору.
    Поддерживает Range-запросы для видео.
    """
    if file_id not in files_metadata:
        raise HTTPException(status_code=404, detail="Файл не найден")

    meta = files_metadata[file_id]
    file_path = os.path.join(UPLOAD_DIR, meta['stored_filename'])

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл отсутствует")

    return FileResponse(
        path=file_path,
        filename=meta['original_filename'],
        media_type=meta.get('content_type', 'application/octet-stream')
    )


@app.get("/files")
async def list_files():
    """Возвращает список всех загруженных файлов."""
    result = []
    for fid, meta in files_metadata.items():
        result.append({
            "file_id": fid,
            "original_filename": meta["original_filename"],
            "size_bytes": meta["size_bytes"],
            "upload_time": meta["upload_time"],
            "download_url": f"/files/{fid}",
            "file_type": meta["file_type"],
            "content_type": meta["content_type"],
        })
    return {"files": result}


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
    """HTML-страница с предпросмотром файлов."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Файлообменник</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; max-width: 1200px; margin: 0 auto; padding: 20px; }
            .file-item { margin: 10px 0; padding: 15px; border: 1px solid #ddd; border-radius: 8px; display: flex; align-items: center; gap: 15px; transition: background 0.2s; }
            .file-item:hover { background: #f9f9f9; }
            .file-item img { width: 80px; height: 60px; object-fit: cover; border-radius: 5px; cursor: pointer; border: 1px solid #eee; }
            .file-item video { width: 80px; height: 60px; object-fit: cover; border-radius: 5px; cursor: pointer; border: 1px solid #eee; }
            button { padding: 8px 15px; cursor: pointer; border: none; border-radius: 5px; background: #007bff; color: white; font-size: 14px; }
            button:hover { background: #0056b3; }
            button.delete { background: #dc3545; }
            button.delete:hover { background: #c82333; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 1000; }
            .modal-content { position: relative; margin: 2% auto; padding: 20px; background: white; width: 90%; max-width: 1000px; max-height: 90vh; overflow: auto; border-radius: 10px; }
            .modal img { max-width: 100%; max-height: 80vh; display: block; margin: 0 auto; }
            .modal video { max-width: 100%; max-height: 80vh; display: block; margin: 0 auto; }
            .modal audio { width: 100%; margin: 20px 0; }
            .modal pre { white-space: pre-wrap; word-wrap: break-word; background: #f5f5f5; padding: 20px; border-radius: 5px; max-height: 70vh; overflow: auto; font-size: 14px; line-height: 1.5; }
            .close { position: absolute; top: 10px; right: 20px; font-size: 35px; cursor: pointer; color: #333; z-index: 1001; }
            .close:hover { color: #000; }
            .preview-link { color: #007bff; cursor: pointer; text-decoration: underline; }
            .preview-link:hover { color: #0056b3; }
            .file-info { flex-grow: 1; }
            .file-info strong { font-size: 16px; display: block; margin-bottom: 5px; word-break: break-all; }
            .file-info small { color: #666; }
            .file-actions { display: flex; gap: 10px; align-items: center; }
            .video-thumb { position: relative; cursor: pointer; }
            .video-thumb::after { content: "▶"; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 20px; color: white; text-shadow: 0 0 5px rgba(0,0,0,0.5); }
            .audio-icon { font-size: 40px; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>📁 Файлообменник</h1>
        
        <div style="background: #f0f0f0; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
            <h2>Загрузить файл</h2>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" required style="padding: 10px; margin-right: 10px;">
                <button type="submit">Загрузить</button>
            </form>
        </div>
        
        <h2>Список файлов</h2>
        <div id="file-list"></div>
        
        <!-- Модальное окно для предпросмотра -->
        <div id="preview-modal" class="modal">
            <div class="modal-content">
                <span class="close" onclick="closePreview()">&times;</span>
                <div id="preview-content"></div>
            </div>
        </div>

        <script>
            async function loadFiles() {
                const resp = await fetch('/files');
                const data = await resp.json();
                const list = document.getElementById('file-list');
                list.innerHTML = '';
                
                if (data.files.length === 0) {
                    list.innerHTML = '<p style="color: #999; text-align: center; padding: 40px;">Нет загруженных файлов</p>';
                    return;
                }
                
                data.files.forEach(f => {
                    const div = document.createElement('div');
                    div.className = 'file-item';
                    
                    let previewHtml = '';
                    let iconHtml = '';
                    
                    switch(f.file_type) {
                        case 'image':
                            iconHtml = `<img src="/files/${f.file_id}" alt="${f.original_filename}" onclick="openPreview('${f.file_id}', 'image', '${f.content_type}')" loading="lazy">`;
                            break;
                        case 'video':
                            iconHtml = `<div class="video-thumb" onclick="openPreview('${f.file_id}', 'video', '${f.content_type}')">
                                <video src="/files/${f.file_id}" preload="metadata"></video>
                            </div>`;
                            break;
                        case 'audio':
                            iconHtml = `<div class="audio-icon" onclick="openPreview('${f.file_id}', 'audio', '${f.content_type}')">🎵</div>`;
                            break;
                        case 'text':
                            iconHtml = `<span class="preview-link" onclick="openPreview('${f.file_id}', 'text', '${f.content_type}')">📄 Предпросмотр</span>`;
                            break;
                        default:
                            iconHtml = `<span style="font-size: 40px;">📁</span>`;
                    }
                    
                    div.innerHTML = `
                        <div style="min-width: 80px; display: flex; align-items: center; justify-content: center;">
                            ${iconHtml}
                        </div>
                        <div class="file-info">
                            <strong title="${f.original_filename}">${f.original_filename}</strong>
                            <small>${formatSize(f.size_bytes)} — ${new Date(f.upload_time).toLocaleString('ru-RU')}</small>
                        </div>
                        <div class="file-actions">
                            <a href="/files/${f.file_id}" download><button>Скачать</button></a>
                            <button class="delete" onclick="deleteFile('${f.file_id}')">Удалить</button>
                        </div>
                    `;
                    
                    list.appendChild(div);
                });
            }
            
            function formatSize(bytes) {
                if (bytes === 0) return '0 B';
                const k = 1024;
                const sizes = ['B', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
            }
            
            async function openPreview(fileId, type, mimeType) {
                const modal = document.getElementById('preview-modal');
                const content = document.getElementById('preview-content');
                
                switch(type) {
                    case 'image':
                        content.innerHTML = `<img src="/files/${fileId}" alt="Предпросмотр">`;
                        break;
                    case 'video':
                        content.innerHTML = `
                            <video controls autoplay>
                                <source src="/files/${fileId}" type="${mimeType}">
                                Ваш браузер не поддерживает видео.
                            </video>`;
                        break;
                    case 'audio':
                        content.innerHTML = `
                            <div style="text-align: center; padding: 40px;">
                                <h3>🎵 Аудиоплеер</h3>
                                <audio controls autoplay style="width: 100%; margin: 20px 0;">
                                    <source src="/files/${fileId}" type="${mimeType}">
                                    Ваш браузер не поддерживает аудио.
                                </audio>
                            </div>`;
                        break;
                    case 'text':
                        try {
                            const resp = await fetch(`/files/${fileId}`);
                            if (!resp.ok) throw new Error('Ошибка загрузки');
                            const text = await resp.text();
                            const escaped = text
                                .replace(/&/g, '&amp;')
                                .replace(/</g, '&lt;')
                                .replace(/>/g, '&gt;');
                            content.innerHTML = `<pre>${escaped}</pre>`;
                        } catch (e) {
                            content.innerHTML = '<p style="color: red; text-align: center;">Не удалось загрузить предпросмотр</p>';
                        }
                        break;
                }
                
                modal.style.display = 'block';
                document.body.style.overflow = 'hidden';
            }
            
            function closePreview() {
                const modal = document.getElementById('preview-modal');
                const content = document.getElementById('preview-content');
                
                // Останавливаем видео/аудио при закрытии
                const media = content.querySelector('video, audio');
                if (media) {
                    media.pause();
                    media.src = '';
                }
                
                content.innerHTML = '';
                modal.style.display = 'none';
                document.body.style.overflow = 'auto';
            }
            
            async function deleteFile(id) {
                if (confirm('Вы уверены, что хотите удалить файл?')) {
                    await fetch(`/files/${id}`, { method: 'DELETE' });
                    loadFiles();
                }
            }
            
            // Закрытие модального окна по клику на фон
            document.getElementById('preview-modal').onclick = function(event) {
                if (event.target === this) {
                    closePreview();
                }
            }
            
            // Закрытие по клавише Escape
            document.addEventListener('keydown', function(event) {
                if (event.key === 'Escape') {
                    closePreview();
                }
            });
            
            window.onload = loadFiles;
            setInterval(loadFiles, 10000); // Обновление каждые 10 секунд
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)