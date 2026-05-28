import os
import uuid
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import aiofiles

app = FastAPI(title='Файлообменник')

# Папка для хранения файлов
UPLOAD_DIR = "files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Временное хранилище метаданных (в реальном проекте — БД)
files_metadata = {}


@app.post('/upload')
async def upload_file(file: UploadFile = File(..., description='Файл')):
    """
    Загружает файл на сервер.
    Возвращает уникальный ID, по которому файл можно скачать.
    """
    # Генерируем уникальное имя файла, чтобы избежать конфликтов
    file_id = str(uuid.uuid4())
    # Оригинальное расширение сохраним для удобства
    original_filename = file.filename
    ext = os.path.splitext(original_filename)[1] if original_filename else ""
    stored_filename = f"{file_id}{ext}"

    file_path = os.path.join(UPLOAD_DIR, stored_filename)

    # Асинхронно сохраняем файл на диск
    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)

    # Записываем метаданные
    files_metadata[file_id] = {
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "size_bytes": len(content),
        "upload_time": datetime.now().isoformat(),
    }

    return {
        "file_id": file_id,
        "filename": original_filename,
        "message": "Файл успешно загружен",
        "download_url": f"/files/{file_id}"
    }

@app.get('/files/{file_id}')
async def download_file(file_id: str):
    """
    Скачивание файла по его идентификатору.
    Возвращает оригинальное имя файла.
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
        media_type="application/octet-stream"
    )


@app.get("/files")
async def list_files():
    """Возвращает список всех загруженных файлов."""
    # Формируем ответ с URL для скачивания
    result = []
    for fid, meta in files_metadata.items():
        result.append({
            "file_id": fid,
            "original_filename": meta["original_filename"],
            "size_bytes": meta["size_bytes"],
            "upload_time": meta["upload_time"],
            "download_url": f"/files/{fid}"
        })
    return {"files": result}


@app.delete('/files/{file_id}')
async def delete_file(file_id: str):
    """Удаляет файл по ID."""
    if file_id not in files_metadata:
        raise HTTPException(status_code=404, detail='Файл не найден')
    
    meta = files_metadata[file_id]
    file_path = os.path.join(UPLOAD_DIR, meta["stored_filename"])
    
    if os.path.exists(file_path):
        os.remove(file_path)
    
    return {"message": f"Файл '{meta['original_filename']}' удалён"}

# Простой веб-интерфейс (опционально) — можно добавить позже
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Минимальная HTML-страница для загрузки файлов через браузер."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Файлообменник</title>
    </head>
    <body>
        <h2>Загрузить файл</h2>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <button type="submit">Загрузить</button>
        </form>
        <hr>
        <h2>Список файлов</h2>
        <ul>
            {{ files_list }}
        </ul>
        <script>
            // Обновляем список файлов каждые 5 секунд (демонстрация)
            async function loadFiles() {
                const resp = await fetch('/files');
                const data = await resp.json();
                const list = document.querySelector('ul');
                list.innerHTML = '';
                data.files.forEach(f => {
                    const li = document.createElement('li');
                    li.innerHTML = `<a href="/files/${f.file_id}">${f.original_filename}</a> (${(f.size_bytes/1024).toFixed(1)} KB) — <button onclick="deleteFile('${f.file_id}')">Удалить</button>`;
                    list.appendChild(li);
                });
            }
            async function deleteFile(id) {
                await fetch(`/files/${id}`, { method: 'DELETE' });
                loadFiles();
            }
            window.onload = loadFiles;
            setInterval(loadFiles, 5000);
        </script>
    </body>
    </html>
    """
    # Грубый рендеринг без шаблонизатора, чтобы не усложнять
    return HTMLResponse(content=html_content)
