import React from "react";
import { Check, X, AlertTriangle, RefreshCw, HelpCircle } from "lucide-react";

export interface TimelineStage {
  id: string;
  name: string;
  emoji: string;
  status: "pending" | "active" | "completed" | "failed" | "retry";
  timeText: string;
}

interface TimelineProps {
  stages: TimelineStage[];
}

export function Timeline({ stages }: TimelineProps) {
  const getIcon = (status: TimelineStage["status"], emoji: string) => {
    switch (status) {
      case "completed":
        return <Check size={12} />;
      case "failed":
        return <X size={12} />;
      case "retry":
        return <AlertTriangle size={12} />;
      case "active":
        return <RefreshCw size={12} className="timeline-spin" />;
      default:
        return <span style={{ fontSize: "0.6875rem" }}>{emoji}</span>;
    }
  };

  return (
    <div className="card-panel" style={{ height: "100%", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      <h3 style={{ fontSize: "0.875rem", fontWeight: 700, color: "white", display: "flex", alignItems: "center", gap: "0.375rem" }}>
        <RefreshCw size={14} className="pulse" />
        Agent Execution Pipeline
      </h3>

      <div className="timeline-list">
        {stages.map((stage) => (
          <div key={stage.id} className={`timeline-item ${stage.status}`}>
            <div className="timeline-icon-box">
              {getIcon(stage.status, stage.emoji)}
            </div>
            <div className="timeline-text">
              <span className="timeline-name">{stage.name}</span>
              <span className="timeline-time">{stage.timeText}</span>
            </div>
          </div>
        ))}
      </div>

      <style>{`
        .timeline-spin {
          animation: spin 1.5s linear infinite;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
