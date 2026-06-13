import React, { useRef, useState } from "react";
import { Upload, FileCode, X } from "lucide-react";

interface FileUploadProps {
  onFileLoad: (code: string, filename: string) => void;
  selectedFilename: string | null;
  onClear: () => void;
}

export function FileUpload({ onFileLoad, selectedFilename, onClear }: FileUploadProps) {
  const [isDragActive, setIsDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const processFile = (file: File) => {
    if (!file) return;
    if (!file.name.endsWith(".py") && file.type !== "text/x-python") {
      alert("Only Python (.py) files are supported.");
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (text) {
        onFileLoad(text, file.name);
      }
    };
    reader.readAsText(file);
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragActive(true);
    } else if (e.type === "dragleave") {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const onButtonClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div
      className="dropzone"
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
      style={{
        borderColor: isDragActive ? "var(--accent-primary)" : "var(--border-color)",
        backgroundColor: isDragActive ? "rgba(59, 130, 246, 0.05)" : "",
        marginTop: "0.25rem"
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        accept=".py"
        onChange={handleChange}
      />

      {selectedFilename ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "0.8125rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", color: "var(--status-clean)" }}>
            <FileCode size={16} />
            <span>Uploaded: <strong>{selectedFilename}</strong></span>
          </div>
          <button
            type="button"
            style={{ background: "none", border: "none", color: "var(--text-secondary)", cursor: "pointer", display: "flex", alignItems: "center" }}
            onClick={(e) => {
              e.stopPropagation();
              onClear();
            }}
          >
            <X size={14} />
          </button>
        </div>
      ) : (
        <div onClick={onButtonClick} style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "0.5rem", fontSize: "0.75rem", color: "var(--text-secondary)" }}>
          <Upload size={14} />
          <span>Drag Python file here or <strong>browse</strong></span>
        </div>
      )}
    </div>
  );
}
