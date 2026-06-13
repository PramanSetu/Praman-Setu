import React from "react";
import { HealthInfo } from "../hooks/useApi";
import { Shield, Zap, Database, Activity, RefreshCw } from "lucide-react";

interface HeaderProps {
  health: HealthInfo | null;
  healthStatus: "checking" | "online" | "offline";
  onRefreshHealth: () => void;
}

export function Header({ health, healthStatus, onRefreshHealth }: HeaderProps) {
  return (
    <header className="app-header">
      <div className="header-logo">
        <Shield size={24} color="#a855f7" strokeWidth={2.5} />
        <div>
          <h1>Praman Setu</h1>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.05rem" }}>
            Code Repair & Semantic Guardrail Engine
          </p>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "1.25rem" }}>
        {healthStatus === "online" && health && (
          <div style={{ display: "none", alignItems: "center", gap: "1rem" }} className="md-flex">
            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
              <Zap size={14} color="#f59e0b" />
              <span>Provider: <strong>{health.default_provider}</strong></span>
            </div>
            
            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
              <Database size={14} color="#6366f1" />
              <span>Checkpoints: <strong style={{ color: health.checkpointing ? "var(--status-clean)" : "var(--status-unresolved)" }}>
                {health.checkpointing ? "Enabled" : "Disabled"}
              </strong></span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
              <Activity size={14} color="#10b981" />
              <span>Sandbox: <strong>{health.sandbox_pool_idle} idle</strong></span>
            </div>
          </div>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          {healthStatus === "checking" && (
            <span className="status-badge" style={{ backgroundColor: "var(--bg-tertiary)", color: "var(--text-secondary)" }}>
              <RefreshCw size={12} className="spin" /> Checking…
            </span>
          )}
          {healthStatus === "online" && (
            <span className="status-badge online">
              <span className="pulse" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "var(--status-clean)", display: "inline-block" }}></span>
              Connected
            </span>
          )}
          {healthStatus === "offline" && (
            <span className="status-badge offline" onClick={onRefreshHealth} style={{ cursor: "pointer" }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "var(--status-error)", display: "inline-block" }}></span>
              Unreachable
            </span>
          )}
        </div>
      </div>

      <style>{`
        .md-flex {
          display: none;
        }
        @media (min-width: 768px) {
          .md-flex {
            display: flex;
          }
        }
        .spin {
          animation: spin 1s linear infinite;
        }
      `}</style>
    </header>
  );
}
