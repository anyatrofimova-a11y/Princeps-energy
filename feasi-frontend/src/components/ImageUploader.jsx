import React, { useState, useCallback, useRef } from "react";
import api from "../services/api";

export default function ImageUploader({ onAnalysisComplete, lat, lon, parcelId }) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  const handleFile = useCallback(async (file) => {
    if (!file) return;
    const allowed = ["image/jpeg", "image/png", "image/tiff", "image/webp"];
    if (!allowed.includes(file.type)) {
      setError("Unsupported format. Use JPEG, PNG, TIFF, or WebP.");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setError("File too large (max 50 MB).");
      return;
    }

    setError(null);
    setUploading(true);
    setProgress(20);

    // Thumbnail preview
    const reader = new FileReader();
    reader.onload = (e) => setPreview(e.target.result);
    reader.readAsDataURL(file);

    try {
      setProgress(40);
      const uploadResult = await api.vision.upload(file, lat, lon, parcelId);
      if (!uploadResult?.upload_id) throw new Error("Upload failed");

      setProgress(60);
      const analysis = await api.vision.instantAnalyse(
        uploadResult.upload_id, lat, lon, parcelId,
        "drone" // uploaded images are assumed drone/aerial
      );
      setProgress(100);

      if (onAnalysisComplete) onAnalysisComplete(analysis);
    } catch (err) {
      setError(err.message || "Analysis failed");
    } finally {
      setUploading(false);
    }
  }, [lat, lon, parcelId, onAnalysisComplete]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer?.files?.[0];
    handleFile(file);
  }, [handleFile]);

  const onDragOver = useCallback((e) => { e.preventDefault(); setDragging(true); }, []);
  const onDragLeave = useCallback(() => setDragging(false), []);

  return (
    <div className="image-uploader">
      <div
        className={`image-drop-zone ${dragging ? "dragging" : ""} ${preview ? "has-preview" : ""}`}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => inputRef.current?.click()}
      >
        {preview ? (
          <img src={preview} alt="Preview" className="image-preview-thumb" />
        ) : (
          <div className="drop-zone-content">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <path d="M21 15l-5-5L5 21"/>
            </svg>
            <span>Drop image or click to upload</span>
            <span className="drop-zone-hint">JPEG, PNG, TIFF, WebP (max 50 MB)</span>
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/tiff,image/webp"
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>
      {uploading && (
        <div className="upload-progress-bar">
          <div className="upload-progress-fill" style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && <div className="upload-error">{error}</div>}
    </div>
  );
}
